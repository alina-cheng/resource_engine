import json
import unittest

from app.adapters.base import SourceConfig
from app.adapters.ndp import NdpAdapter
from app.adapters.odrs import OdrsAdapter
from app.hsds.ids import make_id
from app.hsds.validator import HsdsValidator
from app.services.store import ValidationFailed
from tests.helpers import NDP, ODRS, SAMPLES, make_container


class MappingTests(unittest.TestCase):
    def setUp(self):
        self.c = make_container()
        self.v = self.c.validator

    def _all_valid(self, adapter, cfg):
        n = 0
        for batch in adapter.fetch():
            for rec in batch.records:
                n += 1
                for r in adapter.map(rec).resources:
                    self.assertEqual(self.v.errors(r.type, r.data), [], r.type)
        return n

    def test_every_sample_record_maps_to_valid_hsds(self):
        self.assertEqual(self._all_valid(OdrsAdapter(ODRS, self.c.settings), ODRS), 50)
        self.assertEqual(self._all_valid(NdpAdapter(NDP, self.c.settings), NDP), 20)

    def test_ids_are_deterministic_uuids(self):
        a = OdrsAdapter(ODRS, self.c.settings)
        rec = next(iter(a.fetch())).records[0]
        ids1 = [r.id for r in a.map(rec).resources]
        ids2 = [r.id for r in a.map(rec).resources]
        self.assertEqual(ids1, ids2)
        self.assertEqual(make_id("odrs", "service", rec["id"]), next(r.id for r in a.map(rec).resources if r.type == "service"))

    def test_empty_properties_are_omitted(self):
        a = NdpAdapter(NDP, self.c.settings)
        for batch in a.fetch():
            for rec in batch.records:
                for r in a.map(rec).resources:
                    self.assertFalse([k for k, v in r.data.items() if v in (None, "", [], {})], f"{r.type} has empty props")

    def test_schedule_offsets_follow_timezone(self):
        a = NdpAdapter(NDP, self.c.settings)
        sched = [s for b in a.fetch() for rec in b.records for r in a.map(rec).resources if r.type == "service" for s in r.data.get("schedules", []) if s.get("opens_at")]
        self.assertTrue(sched)
        self.assertRegex(sched[0]["opens_at"], r"^\d{2}:\d{2}[+-]\d{2}:\d{2}$")
        self.assertEqual(sched[0]["timezone"], "America/Los_Angeles")

    def test_org_description_gap_policies(self):
        a = OdrsAdapter(ODRS, self.c.settings)
        rec = next(iter(a.fetch())).records[0]
        org = next(r for r in a.map(rec).resources if r.type == "organization")
        self.assertIn("description_missing", org.data["x_resource_engine"]["flags"])
        strict = make_container(org_description_policy="quarantine")
        with self.assertRaises(Exception):
            OdrsAdapter(ODRS, strict.settings).map(rec)


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.c = make_container()

    def test_counts_balance_and_rerun_creates_no_duplicates(self):
        r1 = self.c.ingest.run(ODRS)
        self.assertEqual((r1["received"], r1["stored"], r1["quarantined"]), (50, 50, 0))
        self.assertEqual(r1["received"], r1["stored"] + r1["quarantined"])
        before = self.c.store.counts()
        r2 = self.c.ingest.run(ODRS)
        self.assertEqual(self.c.store.counts(), before)
        self.assertEqual(r2["unchanged"], 50)

    def test_raw_payload_is_kept_as_received(self):
        self.c.ingest.run(ODRS)
        row = self.c.db.one("SELECT blob_key FROM raw_payload")
        self.assertEqual(self.c.blob.get(row["blob_key"]), (SAMPLES / "BayesExport_20250729.json").read_bytes())

    def test_bad_record_is_quarantined_not_dropped(self):
        d = json.loads((SAMPLES / "BayesExport_20250729.json").read_text())
        d["opportunities"][0]["organization"] = {}
        d["opportunities"][1]["locations"][0]["id"] = None
        tmp = self.c.settings.data_dir / "bad.json"
        tmp.write_text(json.dumps(d))
        r = self.c.ingest.run(SourceConfig("odrs", "odrs", str(tmp)))
        self.assertGreaterEqual(r["quarantined"], 1)
        self.assertEqual(r["received"], r["stored"] + r["quarantined"])
        self.assertEqual(self.c.db.one("SELECT COUNT(*) AS n FROM quarantine")["n"], r["quarantined"])
        self.assertTrue(self.c.db.one("SELECT reason FROM quarantine")["reason"])

    def test_every_stored_record_validates(self):
        self.c.ingest.run(ODRS); self.c.ingest.run(NDP)
        for t in ("organization", "service", "location", "service_at_location", "taxonomy_term"):
            for row in self.c.store.all_of_type(t):
                self.assertEqual(self.c.validator.errors(t, row["data"]), [], t)

    def test_clash_between_source_update_and_human_edit_is_surfaced(self):
        self.c.ingest.run(ODRS)
        svc = self.c.store.all_of_type("service")[0]
        self.c.store.apply_patch(svc["id"], {"eligibility_description": "Edited by a specialist"}, "admin", "dana@demo.org")
        d = json.loads((SAMPLES / "BayesExport_20250729.json").read_text())
        opp = next(o for o in d["opportunities"] if str(o["id"]) == svc["data"]["x_resource_engine"]["source"]["record_id"])
        opp["properties"]["elig-description"] = "Changed again at the source"
        tmp = self.c.settings.data_dir / "upd.json"; tmp.write_text(json.dumps(d))
        r = self.c.ingest.run(SourceConfig("odrs", "odrs", str(tmp)))
        self.assertEqual(r["clashes"], 1)
        cur = self.c.store.get(svc["id"])["data"]["eligibility_description"]
        self.assertEqual(cur, "Edited by a specialist")                   # nothing silently overwritten
        crs = self.c.proposals.list(kind="conflict", status="pending")
        self.assertEqual(crs[0]["patch"]["eligibility_description"]["proposed"], "Changed again at the source")

    def test_source_only_update_is_applied_with_history(self):
        self.c.ingest.run(ODRS)
        d = json.loads((SAMPLES / "BayesExport_20250729.json").read_text())
        d["opportunities"][0]["title"] = "Renamed at the source"
        tmp = self.c.settings.data_dir / "upd2.json"; tmp.write_text(json.dumps(d))
        self.c.ingest.run(SourceConfig("odrs", "odrs", str(tmp)))
        sid = make_id("odrs", "service", d["opportunities"][0]["id"])
        self.assertEqual(self.c.store.get(sid)["data"]["name"], "Renamed at the source")
        h = [x for x in self.c.store.history(sid) if x["field_name"] == "name"]
        self.assertEqual((h[0]["actor_type"], h[0]["updated_by"]), ("source", "odrs"))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.c = make_container(); self.c.ingest.run(NDP)
        self.svc = self.c.store.all_of_type("service")[0]

    def test_edit_records_who_what_when(self):
        self.c.store.apply_patch(self.svc["id"], {"wait_time": "2 days"}, "admin", "dana@demo.org", note="call")
        h = self.c.store.history(self.svc["id"])[0]
        self.assertEqual((h["field_name"], h["replacement_value"], h["updated_by"], h["last_action_type"]), ("wait_time", '"2 days"', "dana@demo.org", "update"))
        self.assertTrue(h["last_action_date"])

    def test_invalid_edit_is_blocked_on_save(self):
        with self.assertRaises(ValidationFailed):
            self.c.store.apply_patch(self.svc["id"], {"status": "banana"}, "admin", "dana@demo.org")
        self.assertNotEqual(self.c.store.get(self.svc["id"])["data"]["status"], "banana")

    def test_protected_fields_cannot_be_edited(self):
        with self.assertRaises(ValidationFailed):
            self.c.store.apply_patch(self.svc["id"], {"id": "x"}, "admin", "dana@demo.org")


if __name__ == "__main__":
    unittest.main()
