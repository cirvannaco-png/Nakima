import hashlib
import hmac
import json
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient


def _client():
    from api.router import app

    return TestClient(app)


def test_health_check():
    client = _client()
    r = client.get("/api/v1/health/")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_webhook_rejects_missing_signature():
    client = _client()
    r = client.post("/github/webhook", json={"foo": "bar"})
    assert r.status_code == 401


def test_webhook_rejects_bad_signature():
    client = _client()
    body = json.dumps({"installation": {"id": 1}, "repository": {"full_name": "a/b"}}).encode()
    r = client.post(
        "/github/webhook",
        content=body,
        headers={
            "X-Hub-Signature-256": "sha256=deadbeef",
            "X-GitHub-Event": "issues",
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 401


def test_webhook_ignores_irrelevant_events():
    client = _client()
    body = json.dumps({"action": "created", "installation": {"id": 42}, "repository": {"full_name": "k/r"}}).encode()
    sig = "sha256=" + hmac.new(b"testsecret", body, hashlib.sha256).hexdigest()
    r = client.post(
        "/github/webhook",
        content=body,
        headers={"X-Hub-Signature-256": sig, "X-GitHub-Event": "star", "Content-Type": "application/json"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ignored"


def test_webhook_rejects_repository_without_active_installation_before_auth(monkeypatch):
    from githubapp import app as github_app_module

    class _SessionContext:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def begin(self):
            return self

    monkeypatch.setattr(github_app_module, "AsyncSessionLocal", _SessionContext)
    monkeypatch.setattr(
        github_app_module,
        "require_active_github_repository_installation",
        AsyncMock(side_effect=ValueError("installation is not registered")),
    )

    client = _client()
    body = json.dumps(
        {
            "action": "opened",
            "installation": {"id": 42},
            "repository": {"id": 101, "full_name": "k/r"},
            "issue": {"title": "x", "body": "y", "number": 1},
        }
    ).encode()
    sig = "sha256=" + hmac.new(b"testsecret", body, hashlib.sha256).hexdigest()
    r = client.post(
        "/github/webhook",
        content=body,
        headers={"X-Hub-Signature-256": sig, "X-GitHub-Event": "issues", "Content-Type": "application/json"},
    )
    assert r.status_code == 403
    assert "not registered to an active" in r.json()["detail"]
