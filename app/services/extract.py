"""Fact extraction from website text. Every fact carries the supporting snippet, because a proposed
value without evidence is not a finding (technical doc 7.2). `RuleExtractor` is deterministic (offline
demo, tests, cost control); `LLMExtractor` uses Bedrock for messy real-world pages."""
from __future__ import annotations
import json
import re

from app.adapters.common import DAY_ORDER, norm_time
from app.services.llm import extract_json

DAYS = {"mon": "MO", "tue": "TU", "wed": "WE", "thu": "TH", "fri": "FR", "sat": "SA", "sun": "SU"}
DAY_RE = r"(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*"
TIME_RE = r"\d{1,2}(?::\d{2})?\s*(?:[ap]\.?m\.?)?"
HOURS_RE = re.compile(rf"\b(?P<d1>{DAY_RE})(?:\s*(?:-|–|—|to|through|thru)\s*(?P<d2>{DAY_RE}))?\s*:?\s*"
                      rf"(?P<o>{TIME_RE})\s*(?:-|–|—|to)\s*(?P<c>{TIME_RE})", re.I)
TIMES_RE = re.compile(rf"(?P<o>{TIME_RE})\s*(?:-|–|—|to)\s*(?P<c>{TIME_RE})", re.I)
PHONE_RE = re.compile(r"\(?\b(\d{3})\)?[\s.\-]*(\d{3})[\s.\-]+(\d{4})\b")
CLOSED_RE = re.compile(r"permanently closed|no longer in operation|has closed its doors|ceased operations|"
                       r"this (?:organization|program|office) (?:has )?closed|out of business", re.I)
LANGS = ["English", "Spanish", "Cantonese", "Mandarin", "Vietnamese", "Tagalog", "Korean", "Russian", "Arabic",
         "Hmong", "Farsi", "Japanese", "Punjabi", "Hindi", "French", "Portuguese", "American Sign Language"]


def _clean_time(t: str, other: str) -> str | None:
    t, other = t.replace(".", "").strip(), other.replace(".", "").strip()
    if not re.search(r"[ap]m", t, re.I):
        m = re.search(r"[ap]m", other, re.I)
        if m and int(re.match(r"\d+", t).group(0)) not in (12,):
            t = f"{t}{m.group(0)}"
    return norm_time(t)


def _expand_days(d1: str, d2: str | None) -> list[str]:
    a = DAYS[d1[:3].lower()]
    if not d2:
        return [a]
    b = DAYS[d2[:3].lower()]
    i, j = DAY_ORDER.index(a), DAY_ORDER.index(b)
    return DAY_ORDER[i:j + 1] if i <= j else DAY_ORDER[i:] + DAY_ORDER[:j + 1]


class RuleExtractor:
    name = "rules-v1"

    def extract(self, text: str) -> dict:
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        facts: dict = {"phones": [], "counties": [], "languages": [], "hours": None, "eligibility": None,
                       "closed": None, "about": None}
        for l in lines:
            if CLOSED_RE.search(l) and not facts["closed"]:
                facts["closed"] = {"snip": l[:300]}
            for m in PHONE_RE.finditer(l):
                digits = "".join(m.groups())
                if not any(p["v"] == digits for p in facts["phones"]):
                    facts["phones"].append({"v": digits, "display": f"({m.group(1)}) {m.group(2)}-{m.group(3)}", "snip": l[:300]})
            mc = re.search(r"counties(?: served)?\s*:\s*(.+)", l, re.I)
            if mc:
                for c in re.split(r",| and |;", mc.group(1)):
                    c = re.sub(r"\bcounty\b", "", c, flags=re.I).strip(" .")
                    if c:
                        facts["counties"].append({"v": c.lower(), "display": f"{c.title()} County", "snip": l[:300]})
            else:
                for c in re.findall(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+)?) County\b", l):
                    if re.search(r"serv(?:e|ing|es)", l, re.I) and not any(x["v"] == c.lower() for x in facts["counties"]):
                        facts["counties"].append({"v": c.lower(), "display": f"{c} County", "snip": l[:300]})
            ml = re.search(r"languages?(?: spoken| offered| available)?\s*:\s*(.+)", l, re.I)
            if ml:
                for item in re.split(r",|;|/|\band\b|&", ml.group(1)):
                    name = item.strip(" .")
                    if name and len(name.split()) <= 3 and not any(x["v"] == name.lower() for x in facts["languages"]):
                        facts["languages"].append({"v": name.lower(), "display": name.title() if name.islower() else name, "snip": l[:300]})
            for clause in re.split(r";|\|", l):
                m = TIMES_RE.search(clause)
                if not m:
                    continue
                days: list[str] = []
                prefix = clause[:m.start()]
                for rng in re.finditer(rf"(?P<a>{DAY_RE})\s*(?:-|–|—|to|through|thru)\s*(?P<b>{DAY_RE})", prefix, re.I):
                    days += _expand_days(rng.group("a"), rng.group("b"))
                rest = re.sub(rf"{DAY_RE}\s*(?:-|–|—|to|through|thru)\s*{DAY_RE}", " ", prefix, flags=re.I)
                days += [DAYS[d[:3].lower()] for d in re.findall(DAY_RE, rest, re.I)]
                o, c = _clean_time(m.group("o"), m.group("c")), _clean_time(m.group("c"), m.group("o"))
                if not (days and o and c):
                    continue
                iv = (facts["hours"] or {"intervals": {}, "snip": l[:300]})
                for d in dict.fromkeys(days):
                    iv["intervals"].setdefault(d, [])
                    if (o, c) not in iv["intervals"][d]:
                        iv["intervals"][d].append((o, c))
                facts["hours"] = iv
            me = re.search(r"(?:eligibility|who (?:can|is) (?:apply|eligible))\s*:\s*(.+)", l, re.I)
            if me:
                facts["eligibility"] = {"text": me.group(1).strip(), "snip": l[:400]}
            if not facts["about"]:
                ma = re.match(r"(?:about(?: us)?|mission|overview)\s*:\s*(.{40,})", l, re.I)
                if ma:
                    facts["about"] = {"text": ma.group(1).strip(), "snip": l[:400]}
        if not facts["about"]:
            para = next((l for l in lines if len(l) >= 80 and not re.match(r"(?:phone|hours|counties|languages|eligibility)", l, re.I)), None)
            if para:
                facts["about"] = {"text": para, "snip": para[:400]}
        return facts


class LLMExtractor:  # pragma: no cover - needs Bedrock
    name = "llm-extractor"
    SYSTEM = ("You extract facts from a nonprofit's web page for a community-resource directory. Reply with JSON only. "
              "Include only facts stated on the page; never guess. Every fact needs a short verbatim `snip` from the page.")
    SCHEMA = ('{"phones":[{"display":"(510) 555-0100","snip":""}],"counties":[{"display":"Alameda County","snip":""}],'
              '"languages":[{"display":"Spanish","snip":""}],"hours":[{"days":"Mon-Fri","open":"9:00 AM","close":"5:00 PM","snip":""}],'
              '"eligibility":{"text":"","snip":""},"closed":{"snip":""},"about":{"text":"","snip":""}}')

    def __init__(self, llm):
        self.llm, self.name = llm, f"llm:{llm.name}"

    def extract(self, text: str) -> dict:
        raw = self.llm.complete(self.SYSTEM, f"Schema:\n{self.SCHEMA}\n\nPage text:\n{text[:12000]}", max_tokens=1500)
        data = extract_json(raw) or {}
        facts = {"phones": [], "counties": [], "languages": [], "hours": None, "eligibility": None,
                 "closed": data.get("closed") or None, "about": data.get("about") or None}
        for p in data.get("phones", []):
            m = PHONE_RE.search(p.get("display", ""))
            if m and p.get("snip"):
                facts["phones"].append({"v": "".join(m.groups()), "display": p["display"], "snip": p["snip"]})
        for c in data.get("counties", []):
            n = re.sub(r"\bcounty\b", "", c.get("display", ""), flags=re.I).strip()
            if n and c.get("snip"):
                facts["counties"].append({"v": n.lower(), "display": f"{n.title()} County", "snip": c["snip"]})
        for l in data.get("languages", []):
            if l.get("display") and l.get("snip"):
                facts["languages"].append({"v": l["display"].lower(), "display": l["display"], "snip": l["snip"]})
        for h in data.get("hours", []):
            m = re.match(rf"({DAY_RE})(?:\s*(?:-|–|to)\s*({DAY_RE}))?", h.get("days", ""), re.I)
            o, c = _clean_time(h.get("open", ""), h.get("close", "")), _clean_time(h.get("close", ""), h.get("open", ""))
            if m and o and c and h.get("snip"):
                iv = facts["hours"] or {"intervals": {}, "snip": h["snip"]}
                for d in _expand_days(m.group(1), m.group(2)):
                    iv["intervals"].setdefault(d, []).append((o, c))
                facts["hours"] = iv
        el = data.get("eligibility")
        if el and el.get("text") and el.get("snip"):
            facts["eligibility"] = el
        return facts


def build_extractor(llm):
    return RuleExtractor() if getattr(llm, "is_mock", True) else LLMExtractor(llm)
