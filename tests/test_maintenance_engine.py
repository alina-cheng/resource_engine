"""Tests for the ported AI maintenance detection engine (app.maintenance).

Covers the parts that make the engine trustworthy and that are independent of the Flask app:
the findings contract rules, the extractor's anti-hallucination grounding, and the comparator's
category precedence and evidence-backed findings. These run fully offline with a fake invoker.
"""
import json
import unittest

from app.maintenance.comparator import (
    Comparison,
    PRECEDENCE,
    categorize,
    check_page,
    compare,
    rank_findings,
    triage_tier,
)
from app.maintenance.findings import (
    Category,
    Evidence,
    Finding,
    finding_problems,
)
from app.maintenance.extractor import ModelReply, extract_facts, squash, visible_text
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
    """A user report forces a fresh AI check and raises the single user_reported flag."""

    @classmethod
    def setUpClass(cls):
        from tests.helpers import generated_container
        cls.c, cls.gen = generated_container(20, 10, 7)
        cls.c.maintenance.run(scope="all", force=True, trigger="test", initiated_by="test")
        cls.svc = cls.c.store.list("service", limit=1)[0][0]

    def test_report_forces_recheck_and_raises_flag(self):
        c, svc = self.c, self.svc
        c.maintenance.reports.file(svc["id"], reporter_id="u1", reporter_email="u1@x.org", note="looks wrong")
        # Not forced, not due by age -> would normally be skipped; the report makes it due.
        out = c.maintenance.run(scope="all", force=False, trigger="test", initiated_by="test")
        self.assertGreaterEqual(out["user_reported"], 1)
        row = c.db.one("SELECT flags FROM check_result WHERE resource_id=?", (svc["id"],))
        self.assertIn("user_reported", (row["flags"] or ""))
        # The report is resolved once the record has been rechecked.
        self.assertFalse(c.maintenance.reports.has_open(svc["id"]))

    def test_single_flag_regardless_of_outcome(self):
        # Whatever the check concludes, exactly the one user_reported flag is raised.
        c = self.c
        other = c.store.list("service", limit=2)[0][1]
        c.maintenance.reports.file(other["id"], reporter_id="u2", reporter_email="u2@x.org")
        c.maintenance.run(scope="all", force=False, trigger="test", initiated_by="test")
        flags = json.loads(c.db.one("SELECT flags FROM check_result WHERE resource_id=?", (other["id"],))["flags"] or "[]")
        self.assertEqual(flags, ["user_reported"])
