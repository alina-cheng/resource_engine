"""Corpus coverage, persisted progress and real-extractor routing regressions."""
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.db import dumps, now_iso
from app.maintenance.extractor import ModelReply
from app.maintenance.website_source import WebsiteResult
from tests.helpers import ODRS, make_container


def corpus(size=300):
    c = make_container()
    for i in range(size):
        sid = f"coverage-{i:04d}"
        c.db.run("INSERT INTO resource (id,type,source,data,version,created_at,updated_at) VALUES (?,'service','test',?,1,?,?)",
                 (sid, dumps({"id": sid, "name": sid}), now_iso(), now_iso()))
    return c


def test_manual_check_covers_all_300_and_publishes_progress():
    c = corpus()
    jid = c.jobs.create("maintenance", {"who": "admin"})
    observed = []
    original = c.maintenance.check_service
    def inspect(*args, **kwargs):
        progress = c.jobs.get(jid)["result"]
        observed.append(progress["checked"])
        assert progress["target"] == 300
        return original(*args, **kwargs)
    with patch.object(c.maintenance, "check_service", side_effect=inspect):
        out = c.jobs.execute(jid)
    assert out["checked"] == out["target"] == 300
    assert observed == list(range(300))
    assert c.db.one("SELECT COUNT(*) AS n FROM check_result")["n"] == 300
    assert c.jobs.get(jid)["result"]["checked"] == 300


def test_scheduler_keeps_daily_budget_and_manual_limit_is_respected():
    c = corpus()
    assert c.maintenance.daily_batch() == 12
    out = c.maintenance.run(trigger="scheduled", limit=None)
    assert out["checked"] == 12
    out = c.maintenance.run(trigger="manual", limit=7)
    assert out["checked"] == 7


def test_bounded_sample_workers_persist_all_results():
    c = corpus(30)
    c.maintenance.s = c.settings.with_overrides(maintenance_concurrency=2)
    out = c.maintenance.run(trigger="manual")
    assert out["checked"] == out["target"] == 30
    assert c.db.one("SELECT COUNT(*) AS n FROM check_result")["n"] == 30


def test_record_edit_is_due_without_waiting_30_days():
    c = make_container()
    c.ingest.run(ODRS)
    svc = c.store.list("service", limit=1)[0][0]
    c.maintenance.run(scope="service", service_id=svc["id"])
    assert svc["id"] not in {r["id"] for r in c.maintenance.due_services()}
    c.store.apply_patch(svc["id"], {"wait_time": "Reviewed today"}, "admin", "reviewer")
    assert svc["id"] in {r["id"] for r in c.maintenance.due_services()}


def test_real_extractor_hash_is_restored_and_skips_unchanged_page():
    c = make_container()
    c.ingest.run(ODRS)
    svc = c.store.list("service", limit=1)[0][0]
    c.maintenance._rule_facts = None
    page = "Call us at (510) 555-0100 for assistance."
    c.maintenance._site = SimpleNamespace(get=lambda url: WebsiteResult(page, 200, None))
    invoke = Mock(return_value=ModelReply(json.dumps({"phones": {"value": ["(510) 555-0100"], "quote": page}}), "fake"))
    c.maintenance._invoke = invoke
    first = c.maintenance.check_service(svc, {}, "first")
    second = c.maintenance.check_service(c.store.get(svc["id"]), {}, "second")
    assert first["category"] in ("verified", "discrepancy", "missing_information")
    assert second["skipped"] is True
    assert invoke.call_count == 1
    stored = c.db.one("SELECT record_hash FROM check_result WHERE resource_id=?", (svc["id"],))
    assert len(stored["record_hash"]) == 64


def test_successful_import_queues_corpus_check_when_enabled():
    c = make_container(auto_maintenance_after_import=True)
    c.ingest.run(ODRS)
    c.ingest_all = Mock(return_value=[{"status": "completed", "received": 50}])
    jid = c.jobs.create("import", {"who": "admin"})
    with patch.object(c.jobs, "start", return_value={"job_id": "followup"}) as start:
        out = c.jobs.execute(jid)
    assert out["maintenance_job"]["job_id"] == "followup"
    assert start.call_args.args == ("maintenance",)
    assert start.call_args.kwargs["limit"] == c.maintenance.active_source_count()


def test_empty_model_facts_do_not_verify_a_record():
    from app.maintenance.comparator import compare, Category, PRECEDENCE
    out = compare({"id": "service"}, {}, url="https://example.org", model_id="fake",
                  checked_at="2026-11-04T00:00:00Z", page_text="Welcome to our organization.")
    assert out.category is Category.CHECK_FAILED
    assert PRECEDENCE.index(Category.ACTIVELY_BAD) < PRECEDENCE.index(Category.CHECK_FAILED)
