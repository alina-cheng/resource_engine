"""AI maintenance (priority 2): check stored records against the organization's website,
categorise the result, and propose evidence-backed changes that a person approves. Facts only,
never wording. The website is treated as more accurate than the record in the MVP.

This service drives the ported detection engine (``app.maintenance``) through the bridge
(``app.services.maintenance_bridge``). It preserves the public surface -- ``run``,
``due_services``, ``check_service`` -- and the change_request / check_result write contract, so
the API, UI and existing tests are unchanged. The detection engine itself (extractor,
comparator, worker) replaces the former inline rule comparison.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from app.db import Database, dumps, loads, new_id, now_iso
from app.maintenance.extractor import BedrockInvoker
from app.maintenance.reports import USER_REPORTED_FLAG, ReportService
from app.maintenance.worker import (
    CheckLogEntry,
    WorkerSetupError,
    check_record,
    iso,
    utc_now,
)
from app.services.maintenance_bridge import (
    ChangeRequestSink,
    WebsiteSourceAdapter,
    build_engine_record,
)
from app.services.proposals import ChangeRequests
from app.services.store import HsdsStore

CATEGORIES = ["actively_bad", "check_failed", "discrepancy", "missing_information", "verified"]


class MaintenanceService:
    def __init__(self, settings, db: Database, store: HsdsStore, proposals: ChangeRequests, website, extractor, llm):
        self.s, self.db, self.store, self.proposals = settings, db, store, proposals
        self.website, self.extractor, self.llm = website, extractor, llm
        self._site = WebsiteSourceAdapter(website)
        # The grounded Bedrock extractor runs only when a real (non-mock) LLM is configured;
        # otherwise the offline rule extractor supplies facts, so tests and the demo need no model.
        self._invoke = None if getattr(llm, "is_mock", True) else BedrockInvoker(model_id=settings.bedrock_model_id)
        self._rule_facts = None if not getattr(llm, "is_mock", True) else _RuleFactSource(extractor)
        self.reports = ReportService(db)

    # ---- selection and runs ---------------------------------------------------------------------
    def active_source_count(self) -> int:
        """Number of active service records -- the basis for self-sizing the daily batch."""
        return self.db.one("SELECT COUNT(*) AS n FROM resource WHERE type='service' AND deleted=0")["n"]

    def daily_batch(self) -> int:
        """Checks per scheduled run, derived from the source count so every source is reviewed
        within MAINTENANCE_RECHECK_DAYS. Not hard-coded; scales as the corpus grows.

            batch = ceil(active / recheck_days) * safety_factor, capped by max_batch (0 = uncapped)

        The safety factor adds headroom so normal failures/skips don't let records slip past the
        window. The optional ceiling protects Bedrock throughput/quota, not cost.

        This sizes a scheduled run (``limit`` unset). It does NOT bound a ``force=True`` run nor
        an explicit ``limit``: force means "recheck everything now" and deliberately ignores the
        self-sized batch, so an operator-triggered full recheck at large scale is unbounded (see
        docs/known-limitations.md #12 and the deferred sharding task).
        """
        active = self.active_source_count()
        days = max(1, self.s.maintenance_recheck_days)
        target = math.ceil(active / days)
        batch = math.ceil(target * max(1.0, self.s.maintenance_safety_factor))
        if self.s.maintenance_max_batch and self.s.maintenance_max_batch > 0:
            batch = min(batch, self.s.maintenance_max_batch)
        return max(1, batch) if active else 0

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
        reported = self.reports.open_resource_ids()
        # A scheduled run with no explicit limit self-sizes from the source count so every
        # source is reviewed within the window. An explicit limit (e.g. an admin one-off) wins.
        batch = self.daily_batch()
        effective_limit = limit if limit is not None else (batch or None)
        if scope == "service":
            row = self.store.get(service_id)
            rows = [row] if row and row["type"] == "service" else []
            force = True
        elif force:
            rows = [self.store.get(r["id"]) for r in self.db.q("SELECT id FROM resource WHERE type='service' AND deleted=0 ORDER BY id")][: limit or None]
        else:
            # Due-by-age records (capped at the self-sized batch), plus any record a user has
            # reported (reports are checked even when not yet due). Reported records go first.
            due = self.due_services(effective_limit)
            due_ids = {r["id"] for r in due if r}
            extra = [self.store.get(rid) for rid in reported if rid not in due_ids]
            rows = [r for r in extra if r and r["type"] == "service"] + [r for r in due if r]
        # batch_target is the self-sized cap on the due-by-age slice. `checked` may exceed it,
        # because user-reported records are always added on top, and a force run ignores it.
        counts = {c: 0 for c in CATEGORIES} | {"checked": 0, "proposals": 0, "skipped_unchanged": 0,
                                               "user_reported": 0, "batch_target": effective_limit or 0}
        cache: dict[str, object] = {}
        try:
            for row in rows[:limit] if limit is not None else rows:
                # A reported record is selected for this run and always flagged for a human, but it
                # still respects the hash-skip: the AI re-reviews only if the page changed since the
                # last review. A person looks because a person flagged it, not because the AI did.
                row_reported = row["id"] in reported
                out = self.check_service(row, cache, run_id, force, reported=row_reported)
                counts["checked"] += 1
                if out.get("flagged"):
                    counts["user_reported"] += 1
                if out.get("skipped"):
                    counts["skipped_unchanged"] += 1
                else:
                    counts[out["category"]] += 1
                    counts["proposals"] += out["proposals"]
        except Exception as error:
            self.db.run("UPDATE maintenance_run SET finished_at=?,status='failed',counts=? WHERE id=?",
                        (now_iso(), dumps(counts | {"error": type(error).__name__}), run_id))
            raise
        self.db.run("UPDATE maintenance_run SET finished_at=?, status='completed', counts=? WHERE id=?", (now_iso(), dumps(counts), run_id))
        return {"run_id": run_id, **counts}

    # ---- one record -----------------------------------------------------------------------------
    def _context(self, svc: dict):
        org = self.store.get(svc["org_id"]) if svc["org_id"] else None
        sals = [r for r in self.db.q("SELECT data FROM resource WHERE type='service_at_location' AND deleted=0 AND org_id=?", (svc["org_id"],))
                if loads(r["data"]).get("service_id") == svc["id"]]
        locations = self.store.get_many([loads(r["data"])["location_id"] for r in sals])
        locs = []
        for sal in sals:
            link = loads(sal["data"])
            location = locations.get(link["location_id"])
            if location:
                loc = dict(location["data"])
                for field in ("schedules", "phones", "accessibility"):
                    if link.get(field):
                        loc[field] = list(loc.get(field, [])) + list(link[field])
                locs.append(loc)
        return org, locs

    def _prior_entry(self, svc: dict) -> CheckLogEntry | None:
        """Rebuild the engine's CheckLogEntry from the stored check_result row, so review-need
        skipping works against the existing columns (page_hash + record_version)."""
        prior = self.db.one("SELECT * FROM check_result WHERE resource_id=?", (svc["id"],))
        if not prior:
            return None
        entry = CheckLogEntry(service_id=svc["id"], checked_at=prior["checked_at"])
        entry.category = _category_or_none(prior["category"])
        # A completed review is carried forward only when it verified the page. page_hash stores
        # the engine's content_hash; record_version pins the record the review ran against.
        if prior.get("page_hash") and prior.get("record_version") is not None:
            entry.content_hash = prior["page_hash"]
            entry.record_hash = _record_marker(prior["record_version"])
            entry.reviewed_category = _category_or_none(prior["category"])
            entry.reviewed_at = prior["checked_at"]
        entry.fetch_failed = prior["category"] in ("actively_bad", "check_failed")
        return entry

    def check_service(self, svc: dict, page_cache: dict, run_id: str, force: bool = False,
                      reported: bool = False) -> dict:
        org, locs = self._context(svc)
        url = (org or {}).get("data", {}).get("website") or svc["data"].get("url")
        # A user report always raises the flag and resolves the open reports, whatever the
        # check finds (or even if there's no website to check).
        flags = [USER_REPORTED_FLAG] if reported else []
        if reported:
            self.reports.resolve_for(svc["id"], "maintenance", run_id)
        if not url:
            return self._finish(svc, "check_failed", "No website on record to check against.", None, run_id, None, None, flags=flags)

        record = build_engine_record(self.store, self.db, svc, org, locs)
        # Mark the record hash with the stored version so an applied finding (version bump)
        # forces a fresh review rather than a carried-forward skip.
        checked_at = iso(utc_now())
        prior = self._prior_entry(svc)
        record_marker = _record_marker(svc["version"])

        sink = ChangeRequestSink(svc, self.proposals, self._model_name())
        try:
            comparison, entry = _run_one(
                self, record, url, prior, checked_at, force, record_marker, page_cache
            )
        except WorkerSetupError as exc:
            # Every record would fail the same way; surface it as a failed check for this record.
            return self._finish(svc, "check_failed", str(exc), url, run_id, None, None, flags=flags)

        if comparison is None:  # unchanged since the last review: AI skipped (hash matched)
            # Even when the AI is skipped, a reported record is flagged for human review, so the
            # user_reported flag is persisted on the existing check_result row.
            if flags:
                self.db.run("UPDATE check_result SET checked_at=?, run_id=?, flags=? WHERE resource_id=?",
                            (now_iso(), run_id, dumps(flags), svc["id"]))
            else:
                self.db.run("UPDATE check_result SET checked_at=?, run_id=? WHERE resource_id=?",
                            (now_iso(), run_id, svc["id"]))
            return {"skipped": True, "category": (entry.category.value if entry.category else "verified"),
                    "proposals": 0, "flagged": bool(flags)}

        n = 0
        for finding in comparison.findings:
            try:
                saved = sink.save(finding)
            except Exception:  # noqa: BLE001 - a rejected finding is dropped, never fatal
                continue
            if saved in sink.saved:
                n += 1
        summary = _summarize(comparison)
        page_hash = entry.content_hash if entry.reviewed_category is not None else None
        return self._record_result(svc, comparison.category.value, summary, url, run_id, page_hash, svc["version"], n, flags=flags)

    # ---- persistence ----------------------------------------------------------------------------
    def _record_result(self, svc, category, summary, url, run_id, page_hash, record_version, n, flags=None) -> dict:
        model = self._model_name()
        flags_json = dumps(flags) if flags else None
        self.db.run("INSERT INTO check_result (resource_id,resource_type,org_id,category,summary,url,checked_at,run_id,model,verified_marker,page_hash,record_version,flags) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(resource_id) DO UPDATE SET category=excluded.category, "
                    "summary=excluded.summary, url=excluded.url, checked_at=excluded.checked_at, run_id=excluded.run_id, "
                    "model=excluded.model, verified_marker=excluded.verified_marker, page_hash=excluded.page_hash, record_version=excluded.record_version, flags=excluded.flags",
                    (svc["id"], "service", svc["org_id"], category, summary, url, now_iso(), run_id, model,
                     1 if category == "verified" else 0, page_hash, record_version, flags_json))
        self.store.set_extension(svc["id"], "last_check", {"category": category, "checked_at": now_iso()})
        return {"category": category, "proposals": n, "summary": summary, "flagged": bool(flags)}

    def _finish(self, svc, category, summary, url, run_id, page_hash, record_version, flags=None) -> dict:
        """Backwards-compatible finish for the no-website / setup-error paths (no findings)."""
        return self._record_result(svc, category, summary, url, run_id, page_hash, record_version, 0, flags=flags)

    def _model_name(self) -> str:
        return getattr(self.extractor, "name", "rules") if self.llm.is_mock else (self.s.bedrock_model_id or "bedrock")


# --------------------------------------------------------------------------- #
# Driving the engine for one record
# --------------------------------------------------------------------------- #
def _run_one(service, record, url, prior, checked_at, force, record_marker, page_cache):
    """Run the detection worker for one record, choosing the offline rule facts or the grounded
    Bedrock extractor. Returns (comparison, entry)."""
    if service._rule_facts is not None:
        return service._rule_facts.check(record, url, prior, checked_at, force, record_marker, service._site, page_cache)
    # Grounded Bedrock path.
    return check_record(
        {**record, "_marker": record_marker},
        url=url,
        website_source=service._site,
        invoke=service._invoke,
        previous=prior,
        checked_at=checked_at,
        force=force,
    )


class _RuleFactSource:
    """Offline fact source: resource-engine's deterministic RuleExtractor, adapted to the facts
    shape the ported comparator consumes. Used whenever the LLM is a mock (demo, tests)."""

    def __init__(self, rule_extractor) -> None:
        self._rules = rule_extractor
        self.name = getattr(rule_extractor, "name", "rules")

    def check(self, record, url, prior, checked_at, force, record_marker, site, page_cache):
        from app.maintenance.comparator import Category, check_page, site_loaded
        from app.maintenance.worker import CheckLogEntry, page_hash as _page_hash
        if url not in page_cache:
            page_cache[url] = site.get(url)
        page = page_cache[url]
        entry = CheckLogEntry(service_id=record["id"], checked_at=checked_at, url=url)
        if prior is not None:
            entry.content_hash = prior.content_hash
            entry.record_hash = prior.record_hash
            entry.reviewed_category = prior.reviewed_category
            entry.reviewed_at = prior.reviewed_at
        entry.fetch_failed = not site_loaded(page)
        readable = not entry.fetch_failed and bool((page.content or "").strip())
        marker = None
        if readable:
            marker = _page_hash(page.content or "")
            unchanged = (
                not force
                and entry.content_hash is not None
                and entry.content_hash == marker
                and entry.record_hash == record_marker
                and entry.reviewed_category is not None
            )
            if unchanged:
                entry.category = entry.reviewed_category
                return None, entry
        extraction = None
        if readable:
            facts = self._facts(page.content or "")
            extraction = {"facts": facts, "model_id": self.name}
        comparison = check_page(
            record, page, extraction, url=url, checked_at=checked_at,
            unreachable_before=bool(prior and prior.fetch_failed),
        )
        if extraction is not None and comparison.category is not Category.CHECK_FAILED:
            entry.content_hash = marker
            entry.record_hash = record_marker
            entry.reviewed_category = comparison.category
            entry.reviewed_at = checked_at
        return comparison, entry

    def _facts(self, html: str) -> dict:
        """Map the RuleExtractor output onto the ported comparator's fact schema.

        The comparator reads facts as ``{key: {"value": ..., "quote": ...}}`` with keys
        area_served, phones, languages, hours, eligibility_*, operating_status, emails.
        """
        from app.maintenance.extractor import visible_text
        raw = self._rules.extract(visible_text(html))
        facts: dict = {}
        if raw.get("closed"):
            facts["operating_status"] = {"value": "closed", "quote": raw["closed"]["snip"]}
        if raw.get("phones"):
            quote = raw["phones"][0]["snip"]
            facts["phones"] = {"value": [p["display"] for p in raw["phones"]], "quote": quote}
        if raw.get("counties"):
            quote = raw["counties"][0]["snip"]
            facts["area_served"] = {"value": [c["display"] for c in raw["counties"]], "quote": quote}
        if raw.get("languages"):
            quote = raw["languages"][0]["snip"]
            facts["languages"] = {"value": [l["display"] for l in raw["languages"]], "quote": quote}
        if raw.get("hours"):
            facts["hours"] = {"value": _hours_statements(raw["hours"]["intervals"]), "quote": raw["hours"]["snip"]}
        if raw.get("eligibility"):
            facts["eligibility_income"] = {"value": raw["eligibility"]["text"], "quote": raw["eligibility"]["snip"]}
        return facts


def _hours_statements(intervals: dict) -> list[str]:
    out = []
    for day, pairs in intervals.items():
        for o, c in pairs:
            out.append(f"{day} {o}-{c}")
    return out or ["hours listed"]


def _summarize(comparison) -> str:
    from app.maintenance.comparator import Category
    cat = comparison.category
    if cat is Category.VERIFIED:
        return "The record matches the website."
    if cat is Category.ACTIVELY_BAD:
        return "The website indicates the organization has closed or is unreachable."
    if cat is Category.CHECK_FAILED:
        return comparison.findings[0].evidence[0].snippet if comparison.findings and comparison.findings[0].evidence else "The check could not complete."
    labels = []
    for f in comparison.findings:
        if f.field and f.category in (Category.DISCREPANCY, Category.MISSING_INFORMATION):
            labels.append(f.field)
    uniq = list(dict.fromkeys(labels))
    if cat is Category.MISSING_INFORMATION:
        return "The record lacks: " + ", ".join(uniq) + "." if uniq else "The record is missing information."
    return "The website differs from the record on: " + ", ".join(uniq) + "." if uniq else "The website differs from the record."


def _category_or_none(value):
    from app.maintenance.comparator import Category
    try:
        return Category(value)
    except ValueError:
        return None


def _record_marker(version) -> str:
    """A stable record hash surrogate derived from the stored version, so a version bump (an
    applied finding) forces a fresh review instead of a carried-forward skip."""
    return f"v{version}"
