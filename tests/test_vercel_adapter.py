import hashlib
import os
import sys
import tempfile

import pytest
import requests_mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from deploy_agent.adapters.vercel import VercelAdapter  # noqa: E402
from deploy_agent.models import DeployConfig, DeployRun, DeployStatusState  # noqa: E402


@pytest.fixture
def artifact_dir():
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "index.html"), "w") as f:
        f.write("<html>hi</html>")
    with open(os.path.join(d, "app.js"), "w") as f:
        f.write("console.log('hi')")
    return d


def test_validate_success(artifact_dir):
    adapter = VercelAdapter(credentials={"api_token": "tok"})
    config = DeployConfig(platform="vercel", project_ref="proj123", artifact_path=artifact_dir)
    with requests_mock.Mocker() as m:
        m.get("https://api.vercel.com/v9/projects/proj123", json={"id": "proj123"})
        result = adapter.validate(config)
    assert result.ok


def test_upload_files_computes_real_sha1(artifact_dir):
    adapter = VercelAdapter(credentials={"api_token": "tok"})
    put_calls = []

    with requests_mock.Mocker() as m:

        def record_put(request, context):
            put_calls.append(
                {
                    "digest_header": request.headers.get("x-vercel-digest"),
                    "body": request.body,
                }
            )
            context.status_code = 200
            return {}

        m.put("https://api.vercel.com/v2/files", json=record_put)

        manifest = adapter._upload_files(artifact_dir)

    assert len(manifest) == 2
    assert len(put_calls) == 2

    # Verify the digest sent in the header actually matches sha1 of the body sent
    for call in put_calls:
        expected_sha = hashlib.sha1(call["body"], usedforsecurity=False).hexdigest()
        assert call["digest_header"] == expected_sha

    manifest_files = {m["file"] for m in manifest}
    assert manifest_files == {"index.html", "app.js"}
    for entry in manifest:
        assert "sha" in entry and "size" in entry


def test_execute_sends_correct_deployment_payload(artifact_dir):
    adapter = VercelAdapter(credentials={"api_token": "tok", "team_id": "team_abc"})
    config = DeployConfig(
        platform="vercel", project_ref="proj123", artifact_path=artifact_dir, environment="production"
    )
    plan = adapter.plan(config)

    with requests_mock.Mocker() as m:
        m.put("https://api.vercel.com/v2/files", json={})
        m.post("https://api.vercel.com/v13/deployments", json={"id": "dpl_xyz"})
        run = adapter.execute(config, plan)

    assert run.external_id == "dpl_xyz"
    deployment_request = [r for r in m.request_history if r.url.startswith("https://api.vercel.com/v13/deployments")][0]
    assert deployment_request.qs.get("teamid") == ["team_abc"]
    body = deployment_request.json()
    assert body["project"] == "proj123"
    assert body["target"] == "production"
    assert len(body["files"]) == 2


def test_status_maps_ready_state():
    adapter = VercelAdapter(credentials={"api_token": "tok"})
    run = DeployRun(external_id="dpl_xyz")
    with requests_mock.Mocker() as m:
        m.get(
            "https://api.vercel.com/v13/deployments/dpl_xyz",
            json={"readyState": "READY", "url": "my-app-abc.vercel.app"},
        )
        status = adapter.status(run)
    assert status.state == DeployStatusState.LIVE
    assert status.live_url == "https://my-app-abc.vercel.app"
