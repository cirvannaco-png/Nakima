import os
import sys
import tempfile

import pytest
import requests_mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from deploy_agent.adapters.supabase import SupabaseAdapter  # noqa: E402
from deploy_agent.models import DeployConfig, DeployRun, DeployStatusState  # noqa: E402


@pytest.fixture
def migration_file():
    fd, path = tempfile.mkstemp(suffix=".sql")
    with os.fdopen(fd, "w") as f:
        f.write("ALTER TABLE styles ADD COLUMN embedding vector(1536);")
    return path


def test_migration_marked_high_risk_and_destructive(migration_file):
    adapter = SupabaseAdapter(credentials={"access_token": "tok"})
    config = DeployConfig(
        platform="supabase",
        project_ref="abcd1234",
        artifact_path=migration_file,
        extra={"target": "migration"},
    )
    plan = adapter.plan(config)
    assert plan.risk.value == "high"
    assert plan.destructive is True
    assert plan.reversible is False  # no down_migration_path provided


def test_migration_execute_sends_real_sql_as_query(migration_file):
    adapter = SupabaseAdapter(credentials={"access_token": "tok"})
    config = DeployConfig(
        platform="supabase",
        project_ref="abcd1234",
        artifact_path=migration_file,
        extra={"target": "migration"},
    )
    plan = adapter.plan(config)

    with requests_mock.Mocker() as m:
        m.post(
            "https://api.supabase.com/v1/projects/abcd1234/database/query",
            json={"result": "ok"},
        )
        run = adapter.execute(config, plan)

    sent_body = m.last_request.json()
    with open(migration_file) as f:
        expected_sql = f.read()
    assert sent_body["query"] == expected_sql
    assert run.metadata["target"] == "migration"


def test_migration_rollback_refuses_automation(migration_file):
    adapter = SupabaseAdapter(credentials={"access_token": "tok"})
    run = DeployRun(external_id="migration-abcd1234", metadata={"target": "migration"})
    result = adapter.rollback(run)
    assert not result.ok
    assert "manually" in result.message


def test_edge_function_deploy_and_status():
    adapter = SupabaseAdapter(credentials={"access_token": "tok"})
    fd, fn_path = tempfile.mkstemp(suffix=".ts")
    with os.fdopen(fd, "w") as f:
        f.write("export default () => new Response('ok')")

    config = DeployConfig(
        platform="supabase",
        project_ref="abcd1234",
        artifact_path=fn_path,
        extra={"target": "edge_function", "function_name": "hello"},
    )
    plan = adapter.plan(config)
    assert plan.risk.value == "low"

    with requests_mock.Mocker() as m:
        m.put("https://api.supabase.com/v1/projects/abcd1234/functions/hello", json={"id": "fn_1"})
        run = adapter.execute(config, plan)
        m.get(
            "https://api.supabase.com/v1/projects/abcd1234/functions/hello",
            json={"status": "ACTIVE"},
        )
        status = adapter.status(run)

    assert status.state == DeployStatusState.LIVE
