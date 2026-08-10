import os
import sys
import tempfile

import pytest
import requests_mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from deploy_agent.adapters.netlify import NetlifyAdapter  # noqa: E402
from deploy_agent.models import DeployConfig  # noqa: E402


@pytest.fixture
def artifact_dir():
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "index.html"), "w") as f:
        f.write("<html>hi</html>")
    return d


def test_validate_success(artifact_dir):
    adapter = NetlifyAdapter(credentials={"api_token": "tok"})
    config = DeployConfig(platform="netlify", project_ref="site123", artifact_path=artifact_dir)
    with requests_mock.Mocker() as m:
        m.get("https://api.netlify.com/api/v1/sites/site123", json={"id": "site123"}, status_code=200)
        result = adapter.validate(config)
    assert result.ok
    assert m.last_request.headers["Authorization"] == "Bearer tok"


def test_validate_site_not_found(artifact_dir):
    adapter = NetlifyAdapter(credentials={"api_token": "tok"})
    config = DeployConfig(platform="netlify", project_ref="ghost-site", artifact_path=artifact_dir)
    with requests_mock.Mocker() as m:
        m.get("https://api.netlify.com/api/v1/sites/ghost-site", status_code=404)
        result = adapter.validate(config)
    assert not result.ok
    assert "not found" in result.errors[0]


def test_execute_deploys_real_zip_body(artifact_dir):
    adapter = NetlifyAdapter(credentials={"api_token": "tok"})
    config = DeployConfig(platform="netlify", project_ref="site123", artifact_path=artifact_dir)
    plan = adapter.plan(config)

    with requests_mock.Mocker() as m:
        m.post(
            "https://api.netlify.com/api/v1/sites/site123/deploys",
            json={"id": "deploy_abc"},
            status_code=200,
        )
        run = adapter.execute(config, plan)

    assert run.external_id == "deploy_abc"
    sent_request = m.last_request
    assert sent_request.headers["Content-Type"] == "application/zip"
    assert sent_request.headers["Authorization"] == "Bearer tok"
    # Confirm we actually sent zip bytes, not an empty/garbage body
    assert sent_request.body[:2] == b"PK"  # zip file magic bytes


def test_status_maps_netlify_states():
    adapter = NetlifyAdapter(credentials={"api_token": "tok"})
    run_id = "run-1"
    from deploy_agent.models import DeployRun, DeployStatusState

    run = DeployRun(id=run_id, external_id="deploy_abc")

    with requests_mock.Mocker() as m:
        m.get(
            "https://api.netlify.com/api/v1/deploys/deploy_abc",
            json={"state": "ready", "ssl_url": "https://site123.netlify.app"},
        )
        status = adapter.status(run)

    assert status.state == DeployStatusState.LIVE
    assert status.live_url == "https://site123.netlify.app"


def test_rollback_without_target_fails_clearly():
    adapter = NetlifyAdapter(credentials={"api_token": "tok"})
    from deploy_agent.models import DeployRun

    run = DeployRun(external_id="deploy_abc", metadata={"site_id": "site123"})
    result = adapter.rollback(run)
    assert not result.ok
    assert "restore_to_deploy_id" in result.message
