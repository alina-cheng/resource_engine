"""Bridge between the ported detection engine (`app.maintenance`) and resource-engine services.

The engine talks to three ports -- a website source, an HSDS record reader, and a findings
sink. This module implements all three in terms of resource-engine's existing building blocks:

- ``WebsiteSourceAdapter`` wraps ``app.services.website`` (Sample/Live) and maps its
  ``WebPage`` to the engine's ``WebsiteResult``.
- ``build_engine_record`` assembles the nested HSDS service shape the comparator reads
  (``facts_from_record``) from a flat ``resource`` row plus its org and locations, using the
  same context ``MaintenanceService`` already gathers.
- ``ChangeRequestSink`` translates an engine ``Finding`` into resource-engine's existing
  ``change_request`` ("ai_finding") + evidence write contract, so the review UI, API and the
  existing tests are unchanged.
"""
from __future__ import annotations

import re

from app.hsds.ids import make_id
from app.maintenance.findings import Category, Finding, FindingRejected, finding_problems
from app.maintenance.website_source import WebsiteResult


# --------------------------------------------------------------------------- #
# Website source port
# --------------------------------------------------------------------------- #
class WebsiteSourceAdapter:
    """Adapt resource-engine's website source (``fetch`` -> ``WebPage``) to the engine's
    ``WebsiteSource`` protocol (``get`` -> ``WebsiteResult``)."""

    def __init__(self, website) -> None:
        self._website = website

    # resource-engine uses terse error codes; the engine's fetch-failure classifier reads
    # descriptive text (e.g. "expired certificate", "NXDOMAIN"). Translate so an expired cert
    # or a dead domain is recognised as actively_bad, and a timeout as a (first) failed check.
    _ERROR_TEXT = {
        "expired_certificate": "the website's security certificate has expired",
        "dns_failure": "NXDOMAIN: the website's address does not resolve",
        "connection_refused": "connection refused",
        "timeout": "the request timed out",
        "blocked_by_robots": "blocked by robots.txt",
        "not_in_samples": "the page is not available",
        "tls_error": "a TLS error occurred",
    }

    def get(self, url: str) -> WebsiteResult:
        page = self._website.fetch(url)
        # A WebPage carries (url, status, text, error). The engine treats a non-None error or
        # a non-2xx status as a failed fetch and never a silent skip.
        content = page.text if (page.text and not page.error) else None
        error = page.error
        if error:
            error = self._ERROR_TEXT.get(error, error)
        return WebsiteResult(content=content, status=page.status, error=error)


# --------------------------------------------------------------------------- #
# Record reader: flat resource row -> nested HSDS service the comparator reads
# --------------------------------------------------------------------------- #
def build_engine_record(store, db, svc: dict, org: dict | None, locs: list[dict]) -> dict:
    """Return the nested HSDS service dict ``comparator.facts_from_record`` expects.

    ``facts_from_record`` reads: id, status, url, eligibility_description, minimum_age,
    maximum_age, email, phones, languages, service_areas, and
    ``service_at_locations[].location`` (for phones/schedules/accessibility on the location).
    Phones/schedules on the service, org and locations are all surfaced, matching the way the
    existing MaintenanceService compares against org and location context.
    """
    d = dict(svc["data"])
    record: dict = {"id": svc["id"]}
    # Scalar / list fields read directly off the service document.
    for key in (
        "status",
        "url",
        "eligibility_description",
        "minimum_age",
        "maximum_age",
        "email",
        "phones",
        "languages",
        "schedules",
        "accessibility",
        "contacts",
    ):
        if key in d:
            record[key] = d[key]
    # resource-engine marks counties structurally (``extent_type == "county"``) and may store
    # the bare name ("San Francisco"). The engine's comparator reads counties from the area
    # text, so give a county area a name its parser recognises ("San Francisco County").
    if d.get("service_areas"):
        areas = []
        for a in d["service_areas"]:
            a = dict(a)
            name = str(a.get("name", "")).strip()
            if (a.get("extent_type") == "county" or a.get("description") == "county") and name and "county" not in name.lower():
                a["name"] = f"{name} County"
            areas.append(a)
        record["service_areas"] = areas
    # The organization's website is the page we check; fall back to it for the url and carry
    # the org email/phones so an org-level contact is visible to the comparator.
    if org:
        od = org["data"]
        if not record.get("url") and od.get("website"):
            record["url"] = od["website"]
        if not record.get("email") and od.get("email"):
            record["email"] = od["email"]
        if od.get("phones"):
            record.setdefault("phones", [])
            record["phones"] = list(record["phones"]) + list(od["phones"])
    # Locations become service_at_locations[].location so location phones/hours/accessibility
    # are compared too.
    sals = []
    for loc in locs:
        sals.append({"location": loc})
    if sals:
        record["service_at_locations"] = sals
    return record


# --------------------------------------------------------------------------- #
# Findings sink: engine Finding -> resource-engine change_request + check_result
# --------------------------------------------------------------------------- #
# Fields the engine proposes that resource-engine stores as patchable service fields.
_PATCHABLE_FIELDS = {
    "status",
    "phones",
    "email",
    "languages",
    "service_areas",
    "schedules",
    "accessibility",
    "eligibility_description",
    "minimum_age",
    "maximum_age",
}


class ChangeRequestSink:
    """A ``FindingsSink`` that records engine findings as resource-engine change requests.

    Only field-level findings with a proposed value become change requests (the existing
    "ai_finding" kind). Whole-record findings (verified, check_failed, a site that is gone)
    carry the check's category but have no patch, so they're recorded on ``check_result`` by
    the service, not here. A closure finding has ``field="status"`` and so does become a
    pending change request, exactly as the old pipeline produced.
    """

    def __init__(self, svc: dict, proposals, model: str) -> None:
        self._svc = svc
        self._proposals = proposals
        self._model = model
        self.saved: list[str] = []

    def save(self, finding: Finding) -> str:
        problems = finding_problems(finding)
        if problems:
            raise FindingRejected("; ".join(problems))
        # Whole-record, non-actionable results (verified / check_failed with no field) carry
        # the category only; there's nothing to propose.
        if not finding.field or finding.proposed_value is None:
            return finding.id
        if finding.field not in _PATCHABLE_FIELDS:
            # Unknown field: keep it as a finding id but don't fabricate a patch.
            return finding.id
        evidence = [
            {"field": finding.field, "url": e.url, "snippet": e.snippet, "model": e.model or self._model}
            for e in finding.evidence
            if e.snippet and e.snippet.strip()
        ]
        if not evidence:
            raise FindingRejected("evidence needs a non-empty snippet")
        # Translate the engine's display-string finding into a structured, schema-valid HSDS
        # patch: `current` is the record's actual stored value (so staleness checks compare
        # like with like) and `proposed` is a structured value that validates on apply.
        current, proposed = _structured_patch(self._svc, finding)
        patch = {finding.field: {"current": current, "proposed": proposed}}
        rid = self._proposals.create(
            resource_id=self._svc["id"],
            resource_type=self._svc["type"],
            org_id=self._svc["org_id"],
            kind="ai_finding",
            proposed_by_type="ai",
            proposed_by="ai-maintenance",
            patch=patch,
            evidence=evidence,
            category=finding.category.value,
            title=_title(finding),
        )
        self.saved.append(rid)
        return rid


def _title(finding: Finding) -> str:
    field = finding.field or "record"
    if finding.category is Category.ACTIVELY_BAD:
        return "The website indicates the organization has closed"
    if finding.category is Category.MISSING_INFORMATION:
        return f"{field} is missing from the record; the website states it"
    return f"The website's {field} differs from the record"


_PHONE_RE = re.compile(r"\(?\b(\d{3})\)?[\s.\-]*(\d{3})[\s.\-]+(\d{4})\b")


def _structured_patch(svc: dict, finding: Finding):
    """Return (current, proposed) as structured HSDS values for the finding's field.

    ``current`` is read from the record so staleness checks compare like with like;
    ``proposed`` is built from the finding's proposed display string into the shape the HSDS
    store validates and stores. Mirrors the structured proposals the former MaintenanceService
    produced. Falls back to the raw display strings for fields with no structured form.
    """
    field = finding.field
    data = svc["data"]
    sid = svc["id"]
    current = data.get(field)
    proposed_text = finding.proposed_value or ""

    if field == "phones":
        numbers = [f"({a}) {b}-{c}" for a, b, c in _PHONE_RE.findall(proposed_text)]
        proposed = [
            {"id": make_id("maint", "phone", sid, n), "service_id": sid, "number": n, "type": "voice"}
            for n in dict.fromkeys(numbers)
        ]
        return (current, proposed or current)

    if field == "service_areas":
        # Proposed display is "A County; B County" (or comma-separated county names).
        names = [p.strip() for p in re.split(r"[;,]", proposed_text) if p.strip()]
        keep = [a for a in (current or []) if not _is_county(a)]
        proposed = keep + [
            {"id": make_id("maint", "area", sid, name), "service_id": sid,
             "name": name if name.lower().endswith("county") else f"{name} County",
             "extent_type": "county"}
            for name in dict.fromkeys(names)
        ]
        return (current, proposed)

    if field == "languages":
        names = [p.strip() for p in re.split(r"[;,]", proposed_text) if p.strip()]
        proposed = [
            {"id": make_id("maint", "lang", sid, name), "service_id": sid, "name": name}
            for name in dict.fromkeys(names)
        ]
        return (current, proposed or current)

    if field in ("minimum_age", "maximum_age"):
        try:
            proposed = int(re.search(r"\d+", proposed_text).group(0))
        except (AttributeError, ValueError):
            proposed = proposed_text
        return (current, proposed)

    if field == "schedules":
        from app.adapters.common import weekly_schedules
        from app.hsds.normalize import normalize_document
        intervals = {}
        for day, opens, closes in re.findall(r"\b(MO|TU|WE|TH|FR|SA|SU)\s+(\d{2}:\d{2})-(\d{2}:\d{2})", proposed_text):
            intervals.setdefault(day, []).append((opens, closes))
        if not intervals:
            raise FindingRejected("hours need structured day and time intervals")
        schedules = weekly_schedules("maint", sid, {"service_id": sid}, intervals, "America/Los_Angeles")
        return current, normalize_document({"schedules": schedules})["schedules"]

    if field == "accessibility":
        return current, [{"id": make_id("maint", "accessibility", sid, proposed_text), "description": proposed_text}]

    # status, email, eligibility_description, schedules, accessibility: use the display value.
    # For status, map the engine's "defunct"/"temporarily closed" to the stored vocabulary.
    if field == "status":
        mapping = {"defunct": "inactive", "temporarily closed": "inactive"}
        return (current, mapping.get(proposed_text, proposed_text))
    return (current, proposed_text)


def _is_county(area: dict) -> bool:
    return ("county" in str(area.get("name", "")).lower() or area.get("extent_type") == "county"
            or area.get("description") == "county")
