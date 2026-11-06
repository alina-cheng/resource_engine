"""Maintenance worker core: check one record (fetch -> review-need -> extract -> compare).

Ported from onedegree_resource_engine/maintenance/worker/run_check.py, keeping the detection
path and the review-need hashing (page_hash + record_hash), and the setup-error-vs-record-error
discipline. The due-record selection and run bookkeeping live in
``app.services.maintenance.MaintenanceService``, which owns the check_result / maintenance_run
tables; the user-report recheck policy (report thresholds, cooldown, legitimacy flags) is a
deferred follow-up and is intentionally not ported here.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.maintenance.comparator import (
    Comparison,
    check_page,
    failure,
    site_loaded,
)
from app.maintenance.comparator import Category
from app.maintenance.extractor import (
    MODEL_ID_ENV,
    ExtractionError,
    Invoker,
    ModelNotConfigured,
    extract_facts,
    visible_text,
)
from app.maintenance.website_source import WebsiteResult, WebsiteSource

# Change this when extraction or comparison changes enough that earlier results shouldn't be
# carried forward, so every record is reviewed again.
REVIEW_VERSION = "2"


class WorkerSetupError(RuntimeError):
    """Every record would fail the same way (no model id, Bedrock access denied), so stop."""


@dataclass
class CheckLogEntry:
    """One check of one record: when, the result, and the hashes that allow a later skip."""

    service_id: str
    checked_at: str  # ISO 8601, UTC
    category: Category | None = None
    url: str | None = None
    fetch_failed: bool = False
    note: str = ""
    skipped_unchanged: bool = False
    model_called: bool = False
    model_id: str = ""
    # The last completed AI review, carried from check to check until a new one completes.
    content_hash: str | None = None  # of the reviewed page's visible text
    record_hash: str | None = None  # of the record as it was reviewed
    reviewed_category: Category | None = None
    reviewed_at: str | None = None
    rejected_facts: list[dict[str, Any]] = field(default_factory=list)
    dropped_findings: list[dict[str, Any]] = field(default_factory=list)
    page_warnings: list[str] = field(default_factory=list)
    truncated: bool = False


def page_hash(content: str) -> str:
    """Hash of a page's visible text with whitespace collapsed, so layout-only edits match."""
    text = " ".join(visible_text(content).split())
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def record_hash(record: dict[str, Any]) -> str:
    """Hash of the record, the review version and the configured model.

    Any change to the record, to ``REVIEW_VERSION`` or to ``BEDROCK_MODEL_ID`` means the
    record is reviewed again rather than carried forward.
    """
    import json

    canonical = json.dumps(record, sort_keys=True, default=str, ensure_ascii=False)
    model = os.environ.get(MODEL_ID_ENV, "").strip()
    return hashlib.sha256(f"{REVIEW_VERSION}\n{model}\n{canonical}".encode()).hexdigest()


def iso(moment: datetime) -> str:
    """UTC ISO 8601 with a Z, to the second: the ``checked_at`` format of findings."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_now() -> datetime:
    return datetime.now(UTC)


def _new_entry(
    service_id: str, checked_at: str, url: str | None, previous: CheckLogEntry | None
) -> CheckLogEntry:
    """A log entry that carries the last completed review forward from ``previous``."""
    entry = CheckLogEntry(service_id=service_id, checked_at=checked_at, url=url)
    if previous is not None:
        entry.content_hash = previous.content_hash
        entry.record_hash = previous.record_hash
        entry.reviewed_category = previous.reviewed_category
        entry.reviewed_at = previous.reviewed_at
    return entry


def is_setup_error(exc: Exception) -> bool:
    """Errors that would hit every record: no model id, or Bedrock refusing the request."""
    return isinstance(exc, ModelNotConfigured) or type(exc).__module__.startswith("botocore")


def _fetch(website_source: WebsiteSource, url: str) -> tuple[WebsiteResult, str]:
    """Fetch a page. A source that raises is treated as a fetch that failed."""
    try:
        return website_source.get(url), ""
    except Exception as exc:  # noqa: BLE001 - any fetch failure is a failed check, not a crash
        kind = type(exc).__name__
        return (
            WebsiteResult(content=None, status=None, error=f"{kind} while fetching the page"),
            f"the website source raised {kind}: {exc}",
        )


def check_record(
    record: dict[str, Any],
    *,
    url: str,
    website_source: WebsiteSource,
    invoke: Invoker | None,
    previous: CheckLogEntry | None,
    checked_at: str,
    force: bool = False,
) -> tuple[Comparison | None, CheckLogEntry]:
    """Check one record: fetch, decide whether it needs an AI review, extract, compare.

    Returns the comparison, or ``None`` when the page and record are unchanged since the last
    completed review (then ``entry.category`` carries that review's result forward). Raises
    only for setup errors.
    """
    site, note = _fetch(website_source, url)
    entry = _new_entry(record["id"], checked_at, url, previous)
    entry.fetch_failed = not site_loaded(site)
    entry.note = note
    readable = not entry.fetch_failed and bool(visible_text(site.content or "").strip())

    page = stored = None
    if readable:
        page = page_hash(site.content or "")
        stored = record_hash(record)
        unchanged = (
            not force
            and entry.content_hash is not None
            and entry.content_hash == page
            and entry.record_hash == stored
            and entry.reviewed_category is not None
        )
        if unchanged:
            entry.skipped_unchanged = True
            entry.category = entry.reviewed_category
            entry.note = f"page and record unchanged since the review at {entry.reviewed_at}"
            return None, entry

    extraction = None
    if readable:
        entry.model_called = True
        try:
            extraction = extract_facts(site.content or "", invoke=invoke)
        except ExtractionError as exc:
            entry.note = f"fact extraction failed: {exc}"
            comparison = failure(
                record, Category.CHECK_FAILED, entry.note, url=url, checked_at=checked_at
            )
            return comparison, entry
        entry.model_id = extraction["model_id"]
        entry.rejected_facts = list(extraction["rejected"])
        entry.page_warnings = list(extraction["warnings"])
        entry.truncated = bool(extraction["truncated"])

    comparison = check_page(
        record,
        site,
        extraction,
        url=url,
        checked_at=checked_at,
        unreachable_before=bool(previous and previous.fetch_failed),
    )
    entry.dropped_findings = list(comparison.dropped)
    if extraction is not None and comparison.category is not Category.CHECK_FAILED:
        # A completed review: later checks can carry it forward while nothing changes.
        entry.content_hash = page
        entry.record_hash = stored
        entry.reviewed_category = comparison.category
        entry.reviewed_at = checked_at
    return comparison, entry
