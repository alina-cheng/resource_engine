"""Real PostgreSQL integration tests; each test owns a disposable schema."""
import os
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pytest

from app.config import load_settings
from app.container import build_container
from app.db import new_id
from app.services.store import Conflict
from tests.helpers import NDP, ODRS, SAMPLES
from tests.test_reliability import proposal

pytestmark = [pytest.mark.postgres, pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL to a local test PostgreSQL instance")]


@pytest.fixture
def pg(tmp_path):
    import psycopg
    from psycopg import sql
    base = os.environ["TEST_DATABASE_URL"]
    schema = "test_" + new_id()
    with psycopg.connect(base, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    parts = urlsplit(base)
    query = dict(parse_qsl(parts.query)) | {"options": f"-csearch_path={schema}"}
    url = urlunsplit(parts._replace(query=urlencode(query)))
    c = build_container(load_settings().with_overrides(database_url=url, data_dir=tmp_path))
    try:
        yield c
    finally:
        with psycopg.connect(base, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_pg_import_raw_validation_and_idempotence(pg):
    first = pg.ingest.run(ODRS)
    assert first["stored"] == 50 and first["status"] == "completed"
    before = pg.store.counts()
    assert pg.ingest.run(ODRS)["unchanged"] == 50
    assert pg.store.counts() == before
    run = pg.ingest.run(NDP)
    assert (run["stored"], run["quarantined"], run["partial_records"], run["objects_quarantined"]) == (20, 0, 6, 7)
    raw = pg.db.one("SELECT blob_key FROM raw_payload WHERE source='odrs'")
    assert pg.blob.get(raw["blob_key"]) == (SAMPLES / "BayesExport_20250729.json").read_bytes()
    for kind in pg.store.counts():
        for row in pg.store.all_of_type(kind):
            assert pg.validator.errors(kind, row["data"]) == []


def test_pg_edit_approval_history_and_new_connection(pg):
    pg.ingest.run(ODRS)
    row = pg.store.list("service", limit=1)[0][0]
    pg.store.apply_patch(row["id"], {"fees_description": "Review fee"}, "admin", "first", expected_version=row["version"])
    changed = pg.store.get(row["id"])
    cid = proposal(pg, changed, "Approved fee")
    pg.proposals.approve(cid, "review")
    fresh = build_container(pg.settings)
    assert fresh.proposals.get(cid)["status"] == "applied"
    assert fresh.store.get(row["id"])["data"]["fees_description"] == "Approved fee"
    assert len([h for h in fresh.store.history(row["id"]) if h["field_name"] == "fees_description"]) == 2


def test_pg_concurrent_approvals_apply_once(pg):
    pg.ingest.run(ODRS)
    row = pg.store.list("service", limit=1)[0][0]
    cid = proposal(pg, row)
    def decide(actor):
        try:
            pg.proposals.approve(cid, actor)
            return "applied"
        except Conflict:
            return "conflict"
    with ThreadPoolExecutor(4) as pool:
        assert sorted(pool.map(decide, ["a", "b", "c", "d"])) == ["applied", "conflict", "conflict", "conflict"]
    assert pg.store.get(row["id"])["version"] == row["version"] + 1


def test_pg_existing_schema_upgrade(pg):
    # This fixture owns its entire schema; emulate the pre-flags workflow layout.
    pg.db.run("ALTER TABLE check_result DROP COLUMN flags")
    pg.db.run("DELETE FROM schema_migration")
    pg.db.init_schema()
    pg.db.init_schema()
    assert pg.db.q("SELECT flags FROM check_result") == []
    assert pg.db.q("SELECT record_hash FROM check_result") == []
    assert len(pg.db.q("SELECT * FROM schema_migration")) == 3
