"""AI maintenance (priority 2): check stored records against the organization's website, categorise the
result (R2.2), and propose evidence-backed changes that a person approves (R2.9). Facts only, never
wording (R2.5). The website is treated as more accurate than the record in the MVP (R2.4)."""
from __future__ import annotations
import hashlib
import re
from datetime import datetime, timedelta, timezone

from app.adapters.common import weekly_schedules
from app.db import Database, dumps, loads, new_id, now_iso
from app.hsds.ids import make_id
from app.services.extract import CLOSED_RE
from app.services.proposals import ChangeRequests
from app.services.store import HsdsStore

CATEGORIES = ["actively_bad", "check_failed", "discrepancy", "missing_information", "verified"]
ACTIVELY_BAD_ERRORS = {"expired_certificate", "dns_failure", "connection_refused"}


def _digits(s: str) -> str:
    d = re.sub(r"\D", "", s or "")
    return d[-10:]


def _is_county(area: dict) -> bool:
    return "county" in area.get("name", "").lower() or area.get("extent_type") == "county"


def _strip_offset(t: str | None) -> str | None:
    return re.sub(r"[+-]\d{2}:\d{2}$", "", t) if t else t


class MaintenanceService:
    def __init__(self, settings, db: Database, store: HsdsStore, proposals: ChangeRequests, website, extractor, llm):
        self.s, self.db, self.store, self.proposals = settings, db, store, proposals
        self.website, self.extractor, self.llm = website, extractor, llm

    # ---- selection and runs ---------------------------------------------------------------------
    def due_services(self, limit: int | None = None) -> list[dict]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.s.maintenance_recheck_days)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        rows = self.db.q("SELECT r.id FROM resource r LEFT JOIN check_result c ON c.resource_id=r.id "
                         "WHERE r.type='service' AND r.deleted=0 AND (c.checked_at IS NULL OR c.checked_at < ?) "
                         "ORDER BY COALESCE(c.checked_at,'') ASC, r.id", (cutoff,))
        ids = [r["id"] for r in rows][: limit or None]
        return [self.store.get(i) for i in ids]

    def run(self, scope: str = "all", service_id: str | None = None, trigger: str = "scheduled",
            initiated_by: str = "scheduler", limit: int | None = None, force: bool = False) -> dict:
        run_id = new_id()
        self.db.run("INSERT INTO maintenance_run (id,scope,trigger,initiated_by,started_at,status) VALUES (?,?,?,?,?,'running')",
                    (run_id, scope if scope == "all" else f"service:{service_id}", trigger, initiated_by, now_iso()))
        if scope == "service":
            row = self.store.get(service_id)
            rows = [row] if row and row["type"] == "service" else []
            force = True
        elif force:
            rows = [self.store.get(r["id"]) for r in self.db.q("SELECT id FROM resource WHERE type='service' AND deleted=0 ORDER BY id")][: limit or None]
        else:
            rows = self.due_services(limit)
        counts = {c: 0 for c in CATEGORIES} | {"checked": 0, "proposals": 0, "skipped_unchanged": 0}
        cache: dict[str, object] = {}
        for row in rows:
            out = self.check_service(row, cache, run_id, force)
            counts["checked"] += 1
            if out.get("skipped"):
                counts["skipped_unchanged"] += 1
            else:
                counts[out["category"]] += 1
                counts["proposals"] += out["proposals"]
        self.db.run("UPDATE maintenance_run SET finished_at=?, status='completed', counts=? WHERE id=?", (now_iso(), dumps(counts), run_id))
        return {"run_id": run_id, **counts}

    # ---- one record -----------------------------------------------------------------------------
    def _context(self, svc: dict):
        org = self.store.get(svc["org_id"]) if svc["org_id"] else None
        sals = [r for r in self.db.q("SELECT data FROM resource WHERE type='service_at_location' AND deleted=0 AND org_id=?", (svc["org_id"],))
                if loads(r["data"]).get("service_id") == svc["id"]]
        locs = [x["data"] for x in self.store.get_many([loads(r["data"])["location_id"] for r in sals]).values()]
        return org, locs

    def check_service(self, svc: dict, page_cache: dict, run_id: str, force: bool = False) -> dict:
        org, locs = self._context(svc)
        d = svc["data"]
        url = (org or {}).get("data", {}).get("website") or d.get("url")
        prior = self.db.one("SELECT * FROM check_result WHERE resource_id=?", (svc["id"],))
        if not url:
            return self._finish(svc, "check_failed", "No website on record to check against.", None, [], run_id, None, None)
        if url not in page_cache:
            page_cache[url] = self.website.fetch(url)
        page = page_cache[url]
        # --- failures are findings, not silent skips --------------------------------------------
        if page.error or (page.status and page.status >= 400):
            kind = page.error or f"http_{page.status}"
            bad = kind in ACTIVELY_BAD_ERRORS or page.status in (404, 410)
            msg = {"expired_certificate": "The website's security certificate has expired.",
                   "dns_failure": "The website's address no longer resolves.",
                   "connection_refused": "The website refuses connections."}.get(kind, f"The website could not be checked ({kind}).")
            if page.status in (404, 410):
                msg = f"The website page returns {page.status} (not found)."
            return self._finish(svc, "actively_bad" if bad else "check_failed", msg, url, [], run_id, None, None)
        page_hash = hashlib.sha256(page.text.encode()).hexdigest()[:16]
        if (not force and prior and prior["page_hash"] == page_hash and prior["record_version"] == svc["version"]
                and prior["category"] == "verified"):
            self.db.run("UPDATE check_result SET checked_at=?, run_id=? WHERE resource_id=?", (now_iso(), run_id, svc["id"]))
            return {"skipped": True, "category": "verified", "proposals": 0}
        facts = self.extractor.extract(page.text)
        category, summary, props = self.compare(svc, org, locs, facts, url)
        return self._finish(svc, category, summary, url, props, run_id, page_hash, svc["version"])

    def compare(self, svc, org, locs, facts, url):
        d, props, missing = svc["data"], [], []
        model = getattr(self.extractor, "name", "rules")

        def prop(resource, field, current, proposed, snip, label):
            props.append({"resource": resource, "field": field, "current": current, "proposed": proposed, "label": label,
                          "evidence": [{"field": field, "url": url, "snippet": snip, "model": model}]})

        if facts["closed"]:
            prop(svc, "status", d.get("status"), "inactive", facts["closed"]["snip"], "The website says this organization has closed")
            return "actively_bad", "The website indicates the organization has closed.", props
        # phones
        stored = {_digits(p["number"]) for p in (d.get("phones", []) + [p for l in locs for p in l.get("phones", [])]
                                                 + (org["data"].get("phones", []) if org else []))}
        web = {p["v"]: p for p in facts["phones"]}
        if web and not (stored & set(web)):
            newp = [{"id": make_id("maint", "phone", svc["id"], v), "service_id": svc["id"], "number": p["display"], "type": "voice"}
                    for v, p in web.items()]
            prop(svc, "phones", d.get("phones", []), newp, next(iter(web.values()))["snip"],
                 "Phone number on the website differs from the record")
        # A stored number that appears on the page confirms the record. Extra numbers are ignored: an organization's
        # page usually lists numbers for all its programs, and flagging them per service is noise (R2.5).
        elif not stored and not web:
            missing.append("phone")
        # counties / service area
        cur_counties = {re.sub(r",.*$", "", a["name"]).replace("County", "").replace("county", "").strip().lower()
                        for a in d.get("service_areas", []) if _is_county(a)}
        web_c = {c["v"]: c for c in facts["counties"]}
        if web_c and set(web_c) != cur_counties:
            keep = [a for a in d.get("service_areas", []) if not _is_county(a)]
            new_areas = keep + [{"id": make_id("maint", "area", svc["id"], v), "service_id": svc["id"], "name": c["display"]}
                                for v, c in sorted(web_c.items())]
            lab = (f"Record lists {len(cur_counties)} counties; website lists {len(web_c)}" if cur_counties
                   else "Counties served are missing from the record")
            prop(svc, "service_areas", d.get("service_areas", []), new_areas, next(iter(web_c.values()))["snip"], lab)
            if not cur_counties:
                missing.append("service area")
        # languages
        cur_l = {l["name"].lower() for l in d.get("languages", [])}
        web_l = {l["v"]: l for l in facts["languages"]}
        if web_l and set(web_l) != cur_l:
            new_langs = [{"id": make_id("maint", "lang", svc["id"], v), "service_id": svc["id"], "name": l["display"]} for v, l in web_l.items()]
            prop(svc, "languages", d.get("languages", []), new_langs, next(iter(web_l.values()))["snip"],
                 "Languages on the website differ from the record" if cur_l else "Languages are missing from the record")
            if not cur_l:
                missing.append("languages")
        # hours
        cur_h: dict[str, set] = {}
        for sch in d.get("schedules", []) + [s for l in locs for s in l.get("schedules", [])]:
            if sch.get("freq") == "WEEKLY" and sch.get("opens_at"):
                for day in (sch.get("byday") or "").split(","):
                    cur_h.setdefault(day, set()).add((_strip_offset(sch["opens_at"]), _strip_offset(sch["closes_at"])))
        if facts["hours"]:
            web_h = {k: set(v) for k, v in facts["hours"]["intervals"].items()}
            if web_h != cur_h:
                notes = [s for s in d.get("schedules", []) if not s.get("opens_at")]
                new_sched = notes + weekly_schedules("maint", svc["id"], {"service_id": svc["id"]}, facts["hours"]["intervals"],
                                                      self.s.default_timezone)
                prop(svc, "schedules", d.get("schedules", []), new_sched, facts["hours"]["snip"],
                     "Opening hours on the website differ from the record" if cur_h else "Opening hours are missing from the record")
                if not cur_h:
                    missing.append("hours")
        elif not cur_h:
            missing.append("hours")
        # eligibility: compare facts (numbers, audiences), not wording
        if facts["eligibility"]:
            cur_e = d.get("eligibility_description", "")
            key = lambda t: (set(re.findall(r"\d+%?", t)), {w for w in ("homeless", "veteran", "senior", "youth", "resident", "income", "disab", "famil") if w in t.lower()})
            if not cur_e:
                prop(svc, "eligibility_description", None, facts["eligibility"]["text"], facts["eligibility"]["snip"],
                     "Eligibility is missing from the record")
                missing.append("eligibility")
            elif key(cur_e) != key(facts["eligibility"]["text"]):
                prop(svc, "eligibility_description", cur_e, facts["eligibility"]["text"], facts["eligibility"]["snip"],
                     "Eligibility rules on the website differ from the record")
        elif not d.get("eligibility_description"):
            missing.append("eligibility")
        # organization description gap (HSDS requires one; ODRS supplies none)
        if org and "description_missing" in (org["data"].get("x_resource_engine", {}).get("flags", [])) and facts["about"]:
            prop(org, "description", org["data"].get("description"), facts["about"]["text"][:600], facts["about"]["snip"],
                 "Organization description is missing; the website has one")
        actionable = [p for p in props if p["resource"]["type"] == "service" or p["field"] == "description"]
        diffs = [p for p in actionable if not p["label"].endswith("missing from the record") and "missing; the website" not in p["label"]]
        if diffs:
            return "discrepancy", "; ".join(dict.fromkeys(p["label"] for p in diffs)) + ".", props
        if props or missing:
            fills = sorted(set(missing) | {p["field"] for p in props})
            return "missing_information", "The record lacks: " + ", ".join(fills) + ".", props
        return "verified", "The record matches the website.", props

    def _finish(self, svc, category, summary, url, props, run_id, page_hash, record_version) -> dict:
        n = 0
        for p in props:
            if not p["evidence"] or not p["evidence"][0].get("snippet"):
                continue                                   # no evidence, no finding
            self.proposals.create(
                resource_id=p["resource"]["id"], resource_type=p["resource"]["type"], org_id=p["resource"]["org_id"],
                kind="ai_finding", proposed_by_type="ai", proposed_by="ai-maintenance",
                patch={p["field"]: {"current": p["current"], "proposed": p["proposed"]}}, evidence=p["evidence"],
                category=category, title=p["label"])
            n += 1
        model = getattr(self.extractor, "name", "rules")
        self.db.run("INSERT INTO check_result (resource_id,resource_type,org_id,category,summary,url,checked_at,run_id,model,verified_marker,page_hash,record_version) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(resource_id) DO UPDATE SET category=excluded.category, "
                    "summary=excluded.summary, url=excluded.url, checked_at=excluded.checked_at, run_id=excluded.run_id, "
                    "model=excluded.model, verified_marker=excluded.verified_marker, page_hash=excluded.page_hash, record_version=excluded.record_version",
                    (svc["id"], "service", svc["org_id"], category, summary, url, now_iso(), run_id, model,
                     1 if category == "verified" else 0, page_hash, record_version))
        self.store.set_extension(svc["id"], "last_check", {"category": category, "checked_at": now_iso()})
        return {"category": category, "proposals": n, "summary": summary}
