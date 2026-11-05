"""Tests for the ported AI maintenance detection engine (app.maintenance).

Covers the parts that make the engine trustworthy and that are independent of the Flask app:
the findings contract rules, the extractor's anti-hallucination grounding, and the comparator's
category precedence and evidence-backed findings. These run fully offline with a fake invoker.
"""
import json
import unittest

from app.maintenance.comparator import (
    PRECEDENCE,
    categorize,
    check_page,
    rank_findings,
)
from app.maintenance.findings import (
    Category,
    Evidence,
    Finding,
    finding_problems,
)
from app.maintenance.extractor import ModelReply, extract_facts, visible_text
from app.maintenance.website_source import WebsiteResult


def _finding(**kw):
    base = dict(
        id="f1", service_id="s1", field="phones", current_value="a", proposed_value="b",
        category=Category.DISCREPANCY, confidence=0.9, model_id="m",
        checked_at="2026-11-04T00:00:00Z",
        evidence=[Evidence(url="http://x.org", snippet="the page says b", model="m")],
    )
    base.update(kw)
    return Finding(**base)


class FindingContract(unittest.TestCase):
    def test_valid_finding_has_no_problems(self):
        self.assertEqual(finding_problems(_finding()), [])

    def test_evidence_needs_a_snippet(self):
        f = _finding(evidence=[Evidence(url="http://x.org", snippet="", model="m")])
        self.assertIn("evidence needs a non-empty snippet", finding_problems(f))

    def test_evidence_needs_a_url(self):
        f = _finding(evidence=[Evidence(url="", snippet="s", model="m")])
        self.assertIn("evidence needs a url", finding_problems(f))

    def test_confidence_must_be_in_range(self):
        self.assertIn("confidence must be between 0 and 1", finding_problems(_finding(confidence=1.5)))

    def test_discrepancy_needs_a_proposed_value(self):
        self.assertIn("discrepancy needs a proposed_value", finding_problems(_finding(proposed_value=None)))

    def test_verified_forbids_a_proposed_value(self):
        f = _finding(category=Category.VERIFIED, field=None, proposed_value="x")
        self.assertIn("verified can't have a proposed_value", finding_problems(f))


PAGE = (
    "<html><body>"
    "<h1>Hope House</h1>"
    "<p>We serve Alameda County residents.</p>"
    "<p>Call us at (510) 555-0100.</p>"
    "<p>Languages: Spanish</p>"
    "</body></html>"
)


def _reply(obj):
    return lambda system, user: ModelReply(text=json.dumps(obj), model_id="fake-model")


class ExtractorGrounding(unittest.TestCase):
    def test_visible_text_drops_scripts_and_hidden(self):
        html = "<p>shown</p><script>hidden1</script><p style='display:none'>hidden2</p>"
        text = visible_text(html)
        self.assertIn("shown", text)
        self.assertNotIn("hidden1", text)
        self.assertNotIn("hidden2", text)

    def test_grounded_fact_is_kept(self):
        facts = extract_facts(PAGE, invoke=_reply({
            "area_served": {"value": ["Alameda County"], "quote": "We serve Alameda County residents."},
        }))["facts"]
        self.assertIn("area_served", facts)

    def test_hallucinated_fact_is_dropped(self):
        # The quote does not appear in the page -> dropped and reported.
        result = extract_facts(PAGE, invoke=_reply({
            "languages": {"value": ["Klingon"], "quote": "We offer services in Klingon."},
        }))
        self.assertNotIn("languages", result["facts"])
        self.assertTrue(any(r["fact"] == "languages" for r in result["rejected"]))

    def test_value_not_in_quote_is_dropped(self):
        # Quote is in the page but doesn't contain the claimed value.
        result = extract_facts(PAGE, invoke=_reply({
            "phones": {"value": ["(999) 999-9999"], "quote": "Call us at (510) 555-0100."},
        }))
        self.assertNotIn("phones", result["facts"])


class ComparatorCategories(unittest.TestCase):
    def _extraction(self, obj):
        return extract_facts(PAGE, invoke=_reply(obj))

    def test_phone_change_is_a_discrepancy(self):
        record = {"id": "s1", "status": "active", "phones": [{"number": "(510) 111-2222"}]}
        site = WebsiteResult(content=PAGE, status=200, error=None)
        ext = self._extraction({"phones": {"value": ["(510) 555-0100"], "quote": "Call us at (510) 555-0100."}})
        comp = check_page(record, site, ext, url="http://x.org", checked_at="2026-11-04T00:00:00Z")
        self.assertEqual(comp.category, Category.DISCREPANCY)
        for f in comp.findings:
            self.assertEqual(finding_problems(f), [])

    def test_fetch_failure_without_evidence_is_still_a_finding(self):
        record = {"id": "s1", "status": "active"}
        site = WebsiteResult(content=None, status=None, error="the request timed out")
        comp = check_page(record, site, None, url="http://x.org", checked_at="2026-11-04T00:00:00Z")
        self.assertEqual(comp.category, Category.CHECK_FAILED)
        self.assertTrue(comp.findings)  # never a silent skip

    def test_gone_site_is_actively_bad(self):
        record = {"id": "s1", "status": "active"}
        site = WebsiteResult(content=None, status=404, error="not found")
        comp = check_page(record, site, None, url="http://x.org", checked_at="2026-11-04T00:00:00Z")
        self.assertEqual(comp.category, Category.ACTIVELY_BAD)

    def test_single_category_by_precedence(self):
        findings = [
            _finding(category=Category.VERIFIED, field=None, proposed_value=None),
            _finding(category=Category.DISCREPANCY),
        ]
        self.assertEqual(categorize(findings), Category.DISCREPANCY)
        # Precedence order is honored.
        self.assertLess(PRECEDENCE.index(Category.ACTIVELY_BAD), PRECEDENCE.index(Category.DISCREPANCY))

    def test_triage_ranks_actively_bad_first(self):
        ab = _finding(category=Category.ACTIVELY_BAD, field=None, proposed_value=None)
        disc = _finding(category=Category.DISCREPANCY, confidence=0.9)
        ranked = rank_findings([disc, ab])
        self.assertIs(ranked[0], ab)


if __name__ == "__main__":
    unittest.main()


class UserReportTriggers(unittest.TestCase):
    """A user report selects the record and always raises the user_reported flag for a human,
    but it still respects the hash-skip: the AI re-reviews only if the page changed."""

    @classmethod
    def setUpClass(cls):
        from tests.helpers import generated_container
        cls.c, cls.gen = generated_container(20, 10, 7)
        # First full run establishes a page hash + category for every record.
        cls.c.maintenance.run(scope="all", force=True, trigger="test", initiated_by="test")
        cls.svc = cls.c.store.list("service", limit=1)[0][0]

    def test_report_on_unchanged_page_skips_ai_but_still_flags(self):
        c, svc = self.c, self.svc
        c.maintenance.reports.file(svc["id"], reporter_id="u1", reporter_email="u1@x.org", note="looks wrong")
        # Page is unchanged since the first run -> AI is skipped, but the record is selected
        # and flagged for a human because a person reported it.
        out = c.maintenance.run(scope="all", force=False, trigger="test", initiated_by="test")
        self.assertGreaterEqual(out["user_reported"], 1)
        self.assertGreaterEqual(out["skipped_unchanged"], 1)  # the reported record hash-skipped
        row = c.db.one("SELECT flags FROM check_result WHERE resource_id=?", (svc["id"],))
        self.assertIn("user_reported", (row["flags"] or ""))
        # The report is resolved once the record has been handled.
        self.assertFalse(c.maintenance.reports.has_open(svc["id"]))

    def test_report_on_changed_page_runs_ai_and_flags(self):
        c = self.c
        other = c.store.list("service", limit=3)[0][2]
        # Change the record so its hash differs -> the report-driven run re-reviews with the AI.
        c.store.apply_patch(other["id"], {"eligibility_description": "Changed eligibility text for the test."},
                            "admin", "tester")
        c.maintenance.reports.file(other["id"], reporter_id="u2", reporter_email="u2@x.org")
        out = c.maintenance.run(scope="all", force=False, trigger="test", initiated_by="test")
        self.assertGreaterEqual(out["user_reported"], 1)
        flags = json.loads(c.db.one("SELECT flags FROM check_result WHERE resource_id=?", (other["id"],))["flags"] or "[]")
        self.assertEqual(flags, ["user_reported"])  # exactly the one flag, whatever the AI concluded


class SelfSizingBatch(unittest.TestCase):
    """The scheduled daily batch is derived from the source count, not hard-coded, so every
    source is reviewed within MAINTENANCE_RECHECK_DAYS and the number scales with the corpus."""

    def _container(self, **overrides):
        from tests.helpers import make_container
        return make_container(**overrides)

    def _add_services(self, c, n):
        # Insert n minimal active service rows directly (no website needed for batch math).
        from app.db import dumps, now_iso
        for i in range(n):
            sid = f"svc-{i:05d}"
            c.db.run(
                "INSERT INTO resource (id,type,org_id,source,status,data,version,created_at,updated_at,deleted) "
                "VALUES (?,?,?,?,?,?,?,?,?,0)",
                (sid, "service", None, "test", "active", dumps({"id": sid, "name": f"S{i}"}), 1, now_iso(), now_iso()))

    def test_batch_scales_with_source_count(self):
        c = self._container(maintenance_recheck_days=30, maintenance_safety_factor=1.2, maintenance_max_batch=0)
        self._add_services(c, 900)
        # 900 / 30 = 30, * 1.2 = 36
        self.assertEqual(c.maintenance.active_source_count(), 900)
        self.assertEqual(c.maintenance.daily_batch(), 36)
        # Grow the corpus: the batch re-derives with no code/config change.
        self._add_services_offset(c, 900, 900)  # add 900 more -> 1800 total
        self.assertEqual(c.maintenance.daily_batch(), 72)  # 1800/30=60 *1.2=72

    def _add_services_offset(self, c, start, n):
        from app.db import dumps, now_iso
        for i in range(start, start + n):
            sid = f"svc-{i:05d}"
            c.db.run(
                "INSERT INTO resource (id,type,org_id,source,status,data,version,created_at,updated_at,deleted) "
                "VALUES (?,?,?,?,?,?,?,?,?,0)",
                (sid, "service", None, "test", "active", dumps({"id": sid, "name": f"S{i}"}), 1, now_iso(), now_iso()))

    def test_max_batch_caps_the_computed_value(self):
        c = self._container(maintenance_recheck_days=30, maintenance_safety_factor=1.2, maintenance_max_batch=50)
        self._add_services(c, 9000)  # 9000/30=300 *1.2=360, capped to 50
        self.assertEqual(c.maintenance.daily_batch(), 50)

    def test_no_sources_is_zero_batch(self):
        c = self._container()
        self.assertEqual(c.maintenance.daily_batch(), 0)

    def test_fifty_thousand_sources_hits_thirty_day_window(self):
        c = self._container(maintenance_recheck_days=30, maintenance_safety_factor=1.0, maintenance_max_batch=0)
        self._add_services(c, 50000)
        batch = c.maintenance.daily_batch()  # ceil(50000/30) = 1667
        self.assertEqual(batch, 1667)
        # 30 days at this batch covers the whole corpus.
        self.assertGreaterEqual(batch * 30, 50000)

    def test_scheduled_run_self_sizes_without_explicit_limit(self):
        c = self._container(maintenance_recheck_days=10, maintenance_safety_factor=1.0, maintenance_max_batch=0)
        self._add_services(c, 100)  # 100/10 = 10 per run
        out = c.maintenance.run(scope="all", trigger="test", initiated_by="test")  # no limit
        self.assertEqual(out["batch_target"], 10)
        self.assertEqual(out["checked"], 10)  # only the self-sized batch is checked

    def test_explicit_limit_overrides_self_sizing(self):
        c = self._container(maintenance_recheck_days=10, maintenance_safety_factor=1.0)
        self._add_services(c, 100)
        out = c.maintenance.run(scope="all", trigger="test", initiated_by="test", limit=5)
        self.assertEqual(out["checked"], 5)


class StructuredPatchTranslation(unittest.TestCase):
    """The bridge translates engine findings into structured, schema-valid HSDS patches without
    degrading the value (regression guard for the status closure signal)."""

    def _svc(self, **data):
        base = {"id": "svc-x", "name": "X", "status": "active"}
        base.update(data)
        return {"id": "svc-x", "type": "service", "org_id": None, "data": base}

    def _finding(self, field, proposed, category=Category.DISCREPANCY):
        return Finding(
            id="f", service_id="svc-x", field=field, current_value="active", proposed_value=proposed,
            category=category, confidence=0.7, model_id="m", checked_at="2026-11-04T00:00:00Z",
            evidence=[Evidence(url="http://x.org", snippet="the org has permanently closed", model="m")],
        )

    def test_permanent_closure_keeps_defunct_not_inactive(self):
        from app.services.maintenance_bridge import _structured_patch
        svc = self._svc()
        _current, proposed = _structured_patch(svc, self._finding("status", "defunct", Category.ACTIVELY_BAD))
        self.assertEqual(proposed, "defunct")  # not downgraded to "inactive"

    def test_temporary_closure_keeps_its_value(self):
        from app.services.maintenance_bridge import _structured_patch
        svc = self._svc()
        _current, proposed = _structured_patch(svc, self._finding("status", "temporarily closed", Category.ACTIVELY_BAD))
        self.assertEqual(proposed, "temporarily closed")

    def test_closure_status_patch_validates_against_hsds(self):
        # The proposed status must be a valid HSDS enum value so apply_patch doesn't reject it.
        from tests.helpers import make_container
        from app.db import dumps, now_iso
        import uuid
        c = make_container()
        sid = str(uuid.uuid4())
        c.db.run("INSERT INTO resource (id,type,org_id,source,status,data,version,created_at,updated_at,deleted) "
                 "VALUES (?,?,?,?,?,?,?,?,?,0)",
                 (sid, "service", None, "t", "active",
                  dumps({"id": sid, "name": "X", "status": "active"}), 1, now_iso(), now_iso()))
        self.assertEqual(c.store.validate_patch(sid, {"status": "defunct"}), [])            # valid HSDS status
        self.assertEqual(c.store.validate_patch(sid, {"status": "temporarily closed"}), []) # valid HSDS status
