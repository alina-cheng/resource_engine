"""ODRS live API transport, with the network faked. The key must never reach stored data or errors."""
import json
import os
import tempfile
import unittest
from glob import glob
from pathlib import Path
from unittest.mock import patch

import requests

from app.adapters.base import Resource, SourceConfig
from app.config import ROOT, load_settings
from tests.helpers import SAMPLES, make_container

KEY = "secret-test-key"
URL = "https://odrs.test:3002/v1/opportunities"
CFG = SourceConfig("odrs", "odrs", URL, options={"api_key_env": "ODRS_API_KEY", "per_page": 2})
RECORDS = json.loads((SAMPLES / "BayesExport_20250729.json").read_text())["opportunities"]


def response(status=200, body=None):
    r = requests.Response()
    r.status_code = status
    r.url = f"{URL}?api_key={KEY}"
    r._content = json.dumps(body or {}).encode()
    return r


def page(n, total_pages=2):
    return response(body={
        "paging": {"total_pages": total_pages, "next_page": f"https://odrs.test/v1/opportunities?api_key={KEY}&page={n + 1}"},
        "opportunities": RECORDS[(n - 1) * 2:n * 2]})


class OdrsApiTests(unittest.TestCase):
    def setUp(self):
        self.c = make_container()
        for p in (patch.dict(os.environ, {"ODRS_API_KEY": KEY}), patch("time.sleep")):
            p.start()
            self.addCleanup(p.stop)

    def _stored_text(self):
        """Everything an import writes that could carry the key."""
        rows = self.c.db.q("SELECT detail FROM import_run") + self.c.db.q("SELECT reason, payload FROM quarantine")
        blobs = [self.c.blob.get(r["blob_key"]).decode() for r in self.c.db.q("SELECT blob_key FROM raw_payload")]
        return json.dumps(rows) + "".join(blobs)

    def test_counts_pages_itself_and_stops_at_the_last(self):
        with patch("requests.get", side_effect=[page(1), page(2)]) as get:
            out = self.c.ingest.run(CFG)
        self.assertEqual(out["status"], "completed")
        self.assertEqual(out["received"], 4)
        self.assertEqual(get.call_count, 2)
        for call, n in zip(get.call_args_list, (1, 2)):
            self.assertEqual(call.args[0], URL)   # never the port-less paging.next_page link
            self.assertEqual(call.kwargs["params"], {"page": n, "per_page": 2, "api_key": KEY})

    def test_key_is_removed_from_stored_payloads(self):
        with patch("requests.get", side_effect=[page(1), page(2)]):
            self.c.ingest.run(CFG)
        stored = self._stored_text()
        self.assertIn("next_page", stored)
        self.assertNotIn(KEY, stored)

    def test_temporary_failures_are_retried(self):
        with patch("requests.get", side_effect=[response(503), requests.ConnectionError("reset"), page(1, total_pages=1)]) as get:
            out = self.c.ingest.run(CFG)
        self.assertEqual(out["status"], "completed")
        self.assertEqual(get.call_count, 3)

    def test_rejected_key_fails_at_once_without_exposing_it(self):
        with patch("requests.get", return_value=response(401)) as get:
            out = self.c.ingest.run(CFG)
        self.assertEqual(get.call_count, 1)
        self.assertEqual(out["status"], "failed")
        self.assertIn("401", out["error"])
        self.assertNotIn(KEY, out["error"])
        self.assertNotIn(KEY, self._stored_text())

    def test_connection_errors_do_not_expose_the_key(self):
        err = requests.ConnectionError(f"failed: {URL}?api_key={KEY}")
        with patch("requests.get", side_effect=err) as get:
            out = self.c.ingest.run(CFG)
        self.assertEqual(get.call_count, 4)
        self.assertEqual(out["status"], "failed")
        self.assertNotIn(KEY, out["error"])

    def test_failure_partway_keeps_earlier_pages(self):
        with patch("requests.get", side_effect=[page(1), response(401)]):
            out = self.c.ingest.run(CFG)
        self.assertEqual(out["status"], "failed")
        self.assertEqual(out["stored"] + out["quarantined"], 2)

    def test_missing_key_is_a_clear_failure(self):
        del os.environ["ODRS_API_KEY"]
        with patch("requests.get") as get:
            out = self.c.ingest.run(CFG)
        get.assert_not_called()
        self.assertEqual(out["status"], "failed")
        self.assertIn("ODRS_API_KEY is not set", out["error"])


    def test_max_pages_limits_the_pull(self):
        cfg = SourceConfig("odrs", "odrs", URL, options={**CFG.options, "max_pages": 1})
        with patch("requests.get", side_effect=[page(1, total_pages=5)]) as get:
            out = self.c.ingest.run(cfg)
        self.assertEqual(out["status"], "completed")
        self.assertEqual(get.call_count, 1)


class OdrsOrgDescriptionTests(unittest.TestCase):
    ORG_URL = "https://odrs.test:3002/v1/organizations"
    CFG = SourceConfig("odrs", "odrs", URL, options={**CFG.options, "organizations_url": ORG_URL})

    def setUp(self):
        self.c = make_container()
        for p in (patch.dict(os.environ, {"ODRS_API_KEY": KEY}), patch("time.sleep")):
            p.start()
            self.addCleanup(p.stop)

    def _api(self, org_response):
        def get(url, params=None, timeout=None):
            return page(params["page"], total_pages=1) if url == URL else org_response
        return get

    def _orgs(self):
        return self.c.store.all_of_type("organization")

    def test_description_comes_from_the_organization_lookup(self):
        org_response = response(body={"description": "<p>Real description</p>"})
        with patch("requests.get", side_effect=self._api(org_response)) as get:
            out = self.c.ingest.run(self.CFG)
        self.assertEqual(out["status"], "completed")
        orgs = self._orgs()
        self.assertTrue(orgs)
        for org in orgs:
            self.assertEqual(org["data"]["description"], "Real description")
            self.assertNotIn("description_missing", org["data"]["x_resource_engine"].get("flags", []))
        org_calls = [c for c in get.call_args_list if c.args[0] != URL]
        self.assertEqual(len(org_calls), len({c.args[0] for c in org_calls}))   # each org looked up once

    def test_failed_lookup_keeps_the_placeholder_and_the_import_continues(self):
        with patch("requests.get", side_effect=self._api(response(404))):
            out = self.c.ingest.run(self.CFG)
        self.assertEqual(out["status"], "completed")
        self.assertEqual(out["stored"], 2)
        for org in self._orgs():
            self.assertIn("description_missing", org["data"]["x_resource_engine"]["flags"])

    def test_org_responses_are_kept_and_counts_still_balance(self):
        org_response = response(body={"description": "Real", "paging_link": f"x?api_key={KEY}"})
        with patch("requests.get", side_effect=self._api(org_response)):
            out = self.c.ingest.run(self.CFG)
        self.assertEqual(out["received"], out["stored"])
        rows = self.c.db.q("SELECT native_id, blob_key FROM raw_payload")
        self.assertTrue(any(r["native_id"].startswith("organization-") for r in rows))
        for r in rows:
            self.assertNotIn(KEY.encode(), self.c.blob.get(r["blob_key"]))


class ReimportTests(unittest.TestCase):
    def setUp(self):
        self.c = make_container()
        self.cfg = SourceConfig("odrs", "odrs", str(SAMPLES / "BayesExport_20250729.json"))
        self.c.ingest.run(self.cfg)

    def test_reimport_survives_rows_with_null_source_info(self):
        row = self.c.db.one("SELECT id, data FROM resource WHERE type='service_at_location' LIMIT 1")
        data = {**json.loads(row["data"]), "x_resource_engine": {"source": None}}
        self.c.db.run("UPDATE resource SET data=? WHERE id=?", (json.dumps(data), row["id"]))
        out = self.c.ingest.run(self.cfg)
        self.assertEqual(out["status"], "completed", out["error"])
        self.assertEqual(out["created"], 0)

    def test_merging_a_record_without_source_info_does_not_store_null(self):
        row = self.c.db.one("SELECT id, data FROM resource WHERE type='taxonomy' LIMIT 1")
        data = json.loads(row["data"])
        self.assertNotIn("x_resource_engine", data)
        res = Resource("taxonomy", row["id"], None, {**data, "description": "Changed by the source"})
        with self.c.db.tx() as t:
            t.run("DELETE FROM resource_source WHERE resource_id=?", (row["id"],))
            t.run("INSERT INTO resource_source (resource_id,source,native_id,fetched_at,snapshot) VALUES (?,?,?,?,?)",
                  (row["id"], "odrs", "x", "2026-01-01", row["data"]))
            out = self.c.store.ingest_upsert(t, "odrs", "x", "2026-01-02", res, None)
        self.assertEqual(out["action"], "updated")
        stored = self.c.store.get(row["id"])["data"]
        self.assertNotIn("source", stored.get("x_resource_engine", {}))


class DotEnvTests(unittest.TestCase):
    def _load(self, env):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".env").write_text("ODRS_API_KEY=from-file\n")
            with patch.dict(os.environ, env, clear=True), patch("app.config.ROOT", Path(d)):
                load_settings()
                return os.environ["ODRS_API_KEY"]

    def test_key_is_read_from_the_env_file(self):
        self.assertEqual(self._load({}), "from-file")

    def test_a_variable_already_set_takes_priority(self):
        self.assertEqual(self._load({"ODRS_API_KEY": "from-shell"}), "from-shell")

    def test_env_file_is_ignored_by_git(self):
        self.assertIn(".env", (ROOT / ".gitignore").read_text().splitlines())


class SourceConfigTests(unittest.TestCase):
    def test_default_sources_use_real_data(self):
        odrs, ndp = json.loads((ROOT / "config" / "sources.json").read_text())
        self.assertTrue(odrs["location"].startswith("https://"))
        self.assertEqual(odrs["options"]["api_key_env"], "ODRS_API_KEY")
        self.assertTrue(odrs["options"]["organizations_url"].startswith("https://"))
        self.assertEqual(len(glob(str(ROOT / ndp["location"]))), 2)
