import json
import unittest
from collections import Counter

from tests.helpers import generated_container


class MaintenanceEvaluation(unittest.TestCase):
    """Seeded evaluation (technical doc 7.4): pages with known truth, measure catches and false flags."""

    @classmethod
    def setUpClass(cls):
        cls.c, cls.gen = generated_container(80, 40, 11)
        cls.summary = cls.c.maintenance.run(scope="all", force=True, trigger="test", initiated_by="test")
        truth = json.loads((cls.gen / "websites_truth.json").read_text())
        cls.scen, cls.exp = truth["scenarios"], truth["expected_categories"]

    def _score(self):
        ok, tot, wrong = Counter(), Counter(), []
        for r in self.c.db.q("SELECT r.org_id, c.category FROM check_result c JOIN resource r ON r.id=c.resource_id"):
            s = self.scen.get(self.c.store.get(r["org_id"])["data"].get("website"))
            if s:
                tot[s] += 1
                ok[s] += r["category"] in self.exp[s]
                if r["category"] not in self.exp[s]:
                    wrong.append((s, r["category"]))
        return ok, tot, wrong

    def test_failures_are_findings_not_silent_skips(self):
        ok, tot, _ = self._score()
        for s in ("not_found", "expired_certificate", "dns_failure", "timeout", "closed"):
            self.assertEqual(ok[s], tot[s], s)

    def test_detects_seeded_discrepancies(self):
        ok, tot, _ = self._score()
        for s in ("phone_changed", "counties_expanded", "languages_changed"):
            self.assertEqual(ok[s], tot[s], s)
        self.assertGreaterEqual(sum(ok.values()) / sum(tot.values()), 0.95)

    def test_false_flag_rate_on_clean_pages_is_low(self):
        ok, tot, _ = self._score()
        self.assertLessEqual(1 - ok["verified"] / tot["verified"], 0.05)

    def test_every_proposal_has_evidence(self):
        for cr in self.c.proposals.list(kind="ai_finding", limit=1000):
            self.assertTrue(cr["evidence"] and cr["evidence"][0]["snippet"] and cr["evidence"][0]["url"], cr["title"])
            if cr["status"] == "applied":                                  # the AI proposes, a person applies
                self.assertTrue(cr["decided_by"])
            else:
                self.assertEqual(cr["status"], "pending")

    def test_unchanged_pages_are_skipped_on_the_next_run(self):
        again = self.c.maintenance.run(scope="all", trigger="test", initiated_by="test", force=False)
        self.assertEqual(again["checked"], 0)                              # nothing due yet
        forced_once = self.c.maintenance.run(scope="all", trigger="test", initiated_by="test", force=True, limit=20)
        self.assertEqual(forced_once["checked"], 20)

    def test_single_record_check_and_verified_marker(self):
        row = self.c.db.one("SELECT resource_id FROM check_result WHERE category='verified' LIMIT 1")
        out = self.c.maintenance.run(scope="service", service_id=row["resource_id"], trigger="test", initiated_by="admin")
        self.assertEqual(out["checked"], 1)
        self.assertEqual(self.c.db.one("SELECT verified_marker FROM check_result WHERE resource_id=?", (row["resource_id"],))["verified_marker"], 1)

    def test_approving_a_finding_updates_the_record_with_ai_attribution(self):
        cr = next(c for c in self.c.proposals.list(kind="ai_finding", status="pending", limit=1000) if "phones" in c["patch"])
        self.c.proposals.approve(cr["id"], "dana@demo.org")
        h = [x for x in self.c.store.history(cr["resource_id"]) if x["field_name"] == "phones"][0]
        self.assertEqual((h["actor_type"], h["updated_by"]), ("ai", "ai-maintenance"))


if __name__ == "__main__":
    unittest.main()
