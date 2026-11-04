"""Helpers shared by adapters."""
from __future__ import annotations
import html
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

from app.hsds.ids import make_id

DAY_CODES = {"mon": "MO", "tue": "TU", "wed": "WE", "thu": "TH", "fri": "FR", "sat": "SA", "sun": "SU",
             "monday": "MO", "tuesday": "TU", "wednesday": "WE", "thursday": "TH", "friday": "FR",
             "saturday": "SA", "sunday": "SU"}
DAY_ORDER = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


class _Strip(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("br", "p", "li", "div"):
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("p", "li", "div"):
            self.out.append("\n")

    def handle_data(self, data):
        self.out.append(data)


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    p = _Strip()
    p.feed(value)
    text = html.unescape("".join(p.out))
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return text or None


def clean(d: dict) -> dict:
    """HSDS rule 4.4.3: omit empty properties instead of sending null/''."""
    return {k: v for k, v in d.items() if v not in (None, "", [], {})}


def utc_offset(tz_name: str, when: datetime | None = None) -> str:
    """UTC offset of `tz_name` at `when` (default now), as +HH:MM / -HH:MM."""
    when = when or datetime.now(timezone.utc)
    off = when.astimezone(ZoneInfo(tz_name)).utcoffset()
    total = int(off.total_seconds() // 60)
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    return f"{sign}{total // 60:02d}:{total % 60:02d}"


def norm_time(t: str | None) -> str | None:
    """'8:00', '08:00', '8am', '5:30 PM' -> '08:00' / '17:30'."""
    if not t:
        return None
    m = re.match(r"^\s*(\d{1,2})(?::(\d{2}))?\s*([ap]m)?\s*$", t.strip().lower())
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    return f"{h:02d}:{mi:02d}" if 0 <= h < 24 and 0 <= mi < 60 else None


def weekly_schedules(src: str, parent_key: str, link: dict, intervals: dict[str, list[tuple[str, str]]],
                     tz_name: str, notes: str | None = None) -> list[dict]:
    """intervals: {'MO': [('08:00','17:00')], ...} -> HSDS weekly schedules, grouping days with
    identical hours. opens_at/closes_at carry the UTC offset (technical doc 4.8); the IANA zone is
    also kept in `timezone` because the offset changes with daylight saving."""
    off = utc_offset(tz_name)
    groups: dict[tuple[str, str], list[str]] = {}
    for day in DAY_ORDER:
        for (o, c) in intervals.get(day, []):
            groups.setdefault((o, c), []).append(day)
    out = []
    for (o, c), days in groups.items():
        out.append(clean({
            "id": make_id(src, "schedule", parent_key, o, c, ",".join(days)),
            **link, "freq": "WEEKLY", "byday": ",".join(days), "opens_at": f"{o}{off}",
            "closes_at": f"{c}{off}", "timezone": tz_name}))
    if notes:
        out.append(clean({"id": make_id(src, "schedule", parent_key, "notes"), **link, "notes": notes,
                          "description": notes}))
    return out


def split_ext(number: str) -> tuple[str, int | None]:
    m = re.match(r"^(.*?)(?:\s*(?:x|ext\.?)\s*(\d+))?\s*$", number.strip(), re.I)
    base = m.group(1).strip() if m else number.strip()
    return base, int(m.group(2)) if m and m.group(2) else None


def phone(src: str, parent_key: str, link: dict, number: str | None, *, ext=None, ptype="voice",
          description=None) -> dict | None:
    if not number:
        return None
    base, ext2 = split_ext(str(number))
    ext = ext if ext not in (None, "") else ext2
    if not base:
        return None
    try:
        ext = int(ext) if ext not in (None, "") else None
    except (TypeError, ValueError):
        ext = None
    return clean({"id": make_id(src, "phone", parent_key, re.sub(r"\D", "", base), ext or ""), **link,
                  "number": base, "extension": ext, "type": ptype, "description": description})


def split_items(text: str | None, seps=r"[;\n]|,(?![^()]*\))") -> list[str]:
    if not text or text.strip().lower() in ("none", "n/a"):
        return []
    return [p.strip(" .") for p in re.split(seps, text) if p and p.strip(" .")]


STATE_COUNTRY = {"united states": "US", "usa": "US", "us": "US", "u.s.": "US"}


def country_code(value: str | None) -> str:
    return STATE_COUNTRY.get((value or "United States").strip().lower(), (value or "US")[:2].upper())


class TaxonomyBuilder:
    """Collects taxonomy + taxonomy_term resources and builds attribute links.

    HSDS defines no service taxonomy of its own: each source brings its own (ODRS:
    areas > categories > tags; NDP: up to 6 levels with codes), kept as separate taxonomies."""

    def __init__(self, src: str, taxonomy_name: str, description: str):
        from app.adapters.base import Resource
        self._R = Resource
        self.src = src
        self.tax_id = make_id(src, "taxonomy", taxonomy_name)
        self.name = taxonomy_name
        self.resources = [Resource("taxonomy", self.tax_id, None,
                                   {"id": self.tax_id, "name": taxonomy_name, "description": description})]
        self._seen = {self.tax_id}

    def term_path(self, names: list[str], code: str | None = None) -> str | None:
        """Create the chain for `names` (root -> leaf); return the leaf term id."""
        parent = None
        leaf = None
        for i, name in enumerate(n for n in names if n):
            tid = make_id(self.src, "taxonomy_term", self.name, *names[: i + 1])
            if tid not in self._seen:
                self._seen.add(tid)
                data = clean({"id": tid, "name": name, "parent_id": parent, "taxonomy": self.name,
                              "taxonomy_id": self.tax_id,
                              "code": code if i == len([n for n in names if n]) - 1 else None})
                self.resources.append(self._R("taxonomy_term", tid, None, data))
            parent, leaf = tid, tid
        return leaf

    def attribute(self, service_id: str, term_id: str) -> dict:
        return {"id": make_id(self.src, "attribute", service_id, term_id), "link_id": service_id,
                "link_entity": "service", "taxonomy_term_id": term_id}
