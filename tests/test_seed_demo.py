"""Seeding a deployed environment must not leak keys, start unbounded model runs or leave unusable logins."""
from dataclasses import replace
from unittest.mock import Mock, patch

import pytest

from app.services.users import CognitoAuth
from tests.helpers import generated_container
from tools.sample_data_generator import seed as seed_mod


class UsernameExists(Exception):
    pass


def real_model(c, env="aws"):
    c.settings = replace(c.settings, env=env, llm_backend="bedrock")
    c.maintenance.run = Mock(return_value={"ran": True})
    return c


def cognito_auth(c):
    auth = CognitoAuth.__new__(CognitoAuth)
    auth.s, auth.users, auth.idp = c.settings, c.users, Mock()
    auth.idp.exceptions.UsernameExistsException = UsernameExists
    c.auth = auth
    return auth


@pytest.fixture
def container():
    c, gen = generated_container()
    seed_mod.GEN = gen
    return c


def test_deployed_seed_skips_keys_and_unbounded_maintenance(container):
    c = real_model(container)
    cognito_auth(c)
    out = seed_mod.seed_demo(c)
    assert "api_keys" not in out
    assert c.db.one("SELECT 1 AS x FROM api_key LIMIT 1") is None
    c.maintenance.run.assert_not_called()
    assert "skipped" in out["maintenance"]


def test_real_model_runs_only_within_the_given_limit(container):
    c = real_model(container)
    cognito_auth(c)
    seed_mod.seed_demo(c, maintenance_limit=5)
    kwargs = c.maintenance.run.call_args.kwargs
    assert kwargs["limit"] == 5
    assert not kwargs.get("force")


def test_cognito_logins_are_created_without_email_and_with_permanent_passwords(container):
    c = real_model(container)
    auth = cognito_auth(c)
    seed_mod.seed_demo(c)
    created = {k.kwargs["Username"]: k.kwargs for k in auth.idp.admin_create_user.call_args_list}
    assert {"admin@demo.org", "provider1@demo.org", "provider5@demo.org", "ana@demo.org", "lena@demo.org"} <= set(created)
    assert all(k["MessageAction"] == "SUPPRESS" for k in created.values())
    passwords = {k.kwargs["Username"]: k.kwargs for k in auth.idp.admin_set_user_password.call_args_list}
    assert passwords["provider2@demo.org"]["Password"] == "demo-provider-2"
    assert all(k["Permanent"] for k in passwords.values())
    groups = {k.kwargs["Username"]: k.kwargs["GroupName"] for k in auth.idp.admin_add_user_to_group.call_args_list}
    assert groups["admin@demo.org"] == "admin" and groups["provider1@demo.org"] == "provider" and groups["ana@demo.org"] == "seeker"
    row = c.users.by_email("provider1@demo.org")
    assert row["org_id"] and not row["password_hash"]


def test_second_run_keeps_existing_data_and_tolerates_existing_cognito_users(container):
    c = real_model(container)
    auth = cognito_auth(c)
    seed_mod.seed_demo(c)
    ana = c.users.by_email("ana@demo.org")
    c.seekers.save_profile(ana["id"], {"zip": "99999"})
    count = lambda table: c.db.one(f"SELECT COUNT(*) AS n FROM {table}")["n"]
    before = {t: count(t) for t in ("users", "help_request", "document", "user_report")}
    assert all(before.values())
    auth.idp.admin_create_user.side_effect = UsernameExists()
    seed_mod.seed_demo(c)
    assert {t: count(t) for t in before} == before
    assert c.seekers.get_profile(ana["id"])["zip"] == "99999"


def test_provider_row_without_organization_gets_linked(container):
    c = real_model(container)
    cognito_auth(c)
    c.users.create("provider1@demo.org", "Staff", "provider")
    seed_mod.seed_demo(c)
    assert c.users.by_email("provider1@demo.org")["org_id"]


def test_local_seed_still_creates_keys_and_runs_mock_maintenance(container):
    out = seed_mod.seed_demo(container)
    assert len(out["api_keys"]) == 2
    assert "skipped" not in out["maintenance"]


def test_cli_no_maintenance_overrides_an_explicit_limit(container):
    from app.jobs.run import main
    c = real_model(container, env="local")
    with patch("app.jobs.run.build_container", return_value=c):
        assert main(["seed-demo", "--no-maintenance", "--limit", "1"]) == 0
    c.maintenance.run.assert_not_called()
