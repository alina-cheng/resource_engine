"""Regression coverage for transaction, upgrade, Cognito and ECS integration failures."""
import os
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from botocore.exceptions import ClientError

from app.db import Database
from app.jobs.runner import JobError
from app.services.proposals import Stale
from app.services.store import Conflict
from app.services.users import AuthError, CognitoAuth, Principal
from tests.helpers import ODRS, make_container


@pytest.fixture
def loaded():
    c = make_container()
    assert c.ingest.run(ODRS)["stored"] == 50
    return c, c.store.list("service", limit=1)[0][0]


def proposal(c, row, value="Proposed fee"):
    return c.proposals.create(resource_id=row["id"], resource_type="service", org_id=row["org_id"],
        kind="provider_update", proposed_by_type="provider", proposed_by="review",
        patch={"fees_description": {"current": row["data"].get("fees_description"), "proposed": value}})


def test_concurrent_approvals_apply_once(loaded):
    c, row = loaded
    cid = proposal(c, row)
    def approve(actor):
        try:
            c.proposals.approve(cid, actor)
            return "applied"
        except Conflict:
            return "conflict"
    with ThreadPoolExecutor(4) as pool:
        assert sorted(pool.map(approve, ["a", "b", "c", "d"])) == ["applied", "conflict", "conflict", "conflict"]
    assert c.store.get(row["id"])["version"] == row["version"] + 1


def test_stale_approval_rolls_back_decision_and_preserves_edit(loaded):
    c, row = loaded
    cid = proposal(c, row)
    c.store.apply_patch(row["id"], {"fees_description": "Newer admin edit"}, "admin", "review")
    with pytest.raises(Stale):
        c.proposals.approve(cid, "review")
    assert c.proposals.get(cid)["status"] == "pending"
    assert c.store.get(row["id"])["data"]["fees_description"] == "Newer admin edit"
    with pytest.raises(Conflict):
        c.store.apply_patch(row["id"], {"fees_description": "stale"}, "admin", "review", expected_version=row["version"])


def test_invalid_approval_saves_neither_decision_nor_history(loaded):
    from app.services.store import ValidationFailed
    c, row = loaded
    cid = proposal(c, row)
    count = len(c.store.history(row["id"]))
    with pytest.raises(ValidationFailed):
        c.proposals.approve(cid, "review", overrides={"fees_description": {"invalid": True}})
    assert c.proposals.get(cid)["status"] == "pending"
    assert len(c.store.history(row["id"])) == count


def test_upgrade_adds_flags_preserves_ids_and_is_idempotent(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'old.db'}")
    db.run("CREATE TABLE check_result (resource_id TEXT PRIMARY KEY, resource_type TEXT NOT NULL, org_id TEXT, category TEXT NOT NULL, summary TEXT, url TEXT, checked_at TEXT NOT NULL, run_id TEXT, model TEXT, verified_marker INTEGER DEFAULT 0, page_hash TEXT, record_version INTEGER)")
    db.run("INSERT INTO check_result (resource_id,resource_type,category,checked_at) VALUES ('existing','service','verified','2026-01-01')")
    db.init_schema()
    db.init_schema()
    assert db.one("SELECT flags FROM check_result WHERE resource_id='existing'") == {"flags": None}
    assert db.one("SELECT record_hash FROM check_result WHERE resource_id='existing'")["record_hash"] is None
    assert len(db.q("SELECT * FROM schema_migration")) == 3


def cognito():
    auth = CognitoAuth.__new__(CognitoAuth)
    auth.s = SimpleNamespace(cognito_client_id="review", jwt_secret="review-secret-at-least-32-characters")
    auth.idp = Mock()
    auth.idp.exceptions = SimpleNamespace(ClientError=ClientError)
    auth.verify = Mock(return_value=Principal("user", "review@example.org", "Review", "admin"))
    return auth


@pytest.mark.parametrize("challenge,answer,key", [
    ("NEW_PASSWORD_REQUIRED", "NewPassword123", "NEW_PASSWORD"),
    ("SOFTWARE_TOKEN_MFA", "123456", "SOFTWARE_TOKEN_MFA_CODE"),
    ("SMS_MFA", "123456", "SMS_MFA_CODE"),
])
def test_cognito_challenge_completes_with_bound_session(challenge, answer, key):
    auth = cognito()
    auth.idp.initiate_auth.return_value = {"ChallengeName": challenge, "Session": "session-value"}
    auth.idp.respond_to_auth_challenge.return_value = {"AuthenticationResult": {"IdToken": "id-token"}}
    first = auth.login("review@example.org", "temporary")
    assert "token" not in first
    result = auth.respond_challenge(first["challenge_token"], answer)
    assert result["user"]["role"] == "admin"
    call = auth.idp.respond_to_auth_challenge.call_args.kwargs
    assert call["Session"] == "session-value"
    assert call["ChallengeResponses"][key] == answer
    with pytest.raises(AuthError):
        auth.respond_challenge("tampered", answer)


def test_cognito_staff_creation_uses_requested_group():
    auth = cognito()
    auth.s.cognito_user_pool_id = "pool"
    auth.create_provider_login("review@example.org", "Review", "admin")
    assert auth.idp.admin_add_user_to_group.call_args.kwargs["GroupName"] == "admin"


def test_ecs_wait_stays_async_and_failed_launch_is_persisted(loaded):
    c, _ = loaded
    ecs = Mock()
    ecs.run_task.return_value = {"tasks": [{"taskArn": "arn:review"}]}
    environment = {"JOB_RUNNER": "ecs", "ECS_CLUSTER": "review", "JOB_TASK_DEFINITION": "review",
                   "JOB_SUBNETS": "subnet", "JOB_SECURITY_GROUPS": "sg"}
    with patch.dict(os.environ, environment), patch("boto3.client", return_value=ecs), patch.object(c.jobs, "_do") as work:
        result = c.jobs.start("maintenance", wait=True, force=True)
        work.assert_not_called()
        row = c.jobs.get(result["job_id"])
        assert row["params"]["force"] is True
        command = ecs.run_task.call_args.kwargs["overrides"]["containerOverrides"][0]["command"]
        assert "--force=True" not in command
        assert f"--job-id={result['job_id']}" in command
        assert row["task_arn"] == "arn:review"
        ecs.run_task.return_value = {"failures": [{"reason": "capacity"}]}
        with pytest.raises(JobError):
            c.jobs.start("maintenance")
    assert c.db.one("SELECT COUNT(*) AS n FROM job_run WHERE status='failed'")["n"] == 1


def test_reported_absent_phone_proposal_is_not_stale():
    from tests.helpers import generated_container
    c, _ = generated_container(80, 40, 11)
    c.maintenance.run(force=True)
    proposals = c.proposals.list(kind="ai_finding", limit=1000)
    assert proposals
    for row in proposals:
        assert c.proposals.stale_fields(row) == []
        assert c.store.validate_patch(row["resource_id"], {k: v["proposed"] for k, v in row["patch"].items()}) == []


def test_bad_parent_cascades_without_removing_independent_organization():
    from app.adapters.transform.partition import partition
    org = {"id": "3d4182c0-a248-4b58-829a-75329fd71d22", "name": "Valid org", "description": "Description"}
    service = {"id": "7d648b08-0799-4822-b205-41043c109fd3", "organization_id": org["id"], "name": "Service", "status": "invalid-status"}
    phone = {"id": "b8b06473-7db4-4592-ad73-b19af2ccf97e", "service_id": service["id"], "number": "510-555-0123"}
    good, bad = partition([("organization", org), ("service", service), ("phone", phone)])
    assert good == [("organization", org)]
    assert {kind for kind, _, _ in bad} == {"service", "phone"}
    assert any("parent service" in message for kind, _, errors in bad if kind == "phone" for message in errors)


def test_reimport_reuses_existing_source_native_public_ids(loaded):
    import uuid
    from app.adapters.base import Mapped, Resource
    c, row = loaded
    legacy_id = str(uuid.uuid4())
    # A prior deployment may use a different UUID rule; match its native identity.
    candidate = Resource("service", legacy_id, row["org_id"], {**row["data"], "id": legacy_id})
    mapped = Mapped("native", [candidate])
    c.ingest._preserve_public_ids(mapped, "odrs")
    assert mapped.resources[0].id == row["id"]
    assert mapped.resources[0].data["id"] == row["id"]


def test_maintenance_failure_does_not_stay_running(loaded):
    c, row = loaded
    with patch.object(c.maintenance, "check_service", side_effect=RuntimeError("test failure")):
        with pytest.raises(RuntimeError):
            c.maintenance.run(scope="service", service_id=row["id"])
    result = c.db.one("SELECT * FROM maintenance_run")
    assert result["status"] == "failed" and result["finished_at"]


def test_schedule_output_honors_reviewed_time_edit():
    from app.hsds.normalize import normalize_document
    schedule = {"opens_at": "10:30-08:00", "closes_at": "17:00-08:00",
                "x_resource_engine": {"local_schedule": {"timezone": "America/Los_Angeles", "opens_at": "09:00", "closes_at": "17:00"}}}
    result = normalize_document({"schedules": [schedule]})
    assert result["schedules"][0]["opens_at"].startswith("10:30")
    assert result["schedules"][0]["x_resource_engine"]["local_schedule"]["opens_at"] == "10:30"
