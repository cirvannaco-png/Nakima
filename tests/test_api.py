import hashlib
import hmac
import json

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
        "/github/webhook", content=body,
        headers={"X-Hub-Signature-256": "sha256=deadbeef", "X-GitHub-Event": "issues", "Content-Type": "application/json"},
    )
    assert r.status_code == 401


def test_webhook_ignores_irrelevant_events():
    client = _client()
    body = json.dumps({"action": "created", "installation": {"id": 42}, "repository": {"full_name": "k/r"}}).encode()
    sig = "sha256=" + hmac.new(b"testsecret", body, hashlib.sha256).hexdigest()
    r = client.post(
        "/github/webhook", content=body,
        headers={"X-Hub-Signature-256": sig, "X-GitHub-Event": "star", "Content-Type": "application/json"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ignored"


def test_webhook_valid_signature_reaches_auth_and_fails_cleanly():
    # installation 42 isn't a real registered GitHub App installation, so
    # this exercises the full pipeline (signature -> parse -> auth attempt)
    # and confirms an auth failure returns a clean 502, not a raw 500 with
    # a stack trace on a public endpoint.
    client = _client()
    body = json.dumps({
        "action": "opened", "installation": {"id": 42},
        "repository": {"full_name": "k/r"}, "issue": {"title": "x", "body": "y", "number": 1},
    }).encode()
    sig = "sha256=" + hmac.new(b"testsecret", body, hashlib.sha256).hexdigest()
    r = client.post(
        "/github/webhook", content=body,
        headers={"X-Hub-Signature-256": sig, "X-GitHub-Event": "issues", "Content-Type": "application/json"},
    )
    assert r.status_code == 502
    assert "Could not authenticate" in r.json()["detail"]
