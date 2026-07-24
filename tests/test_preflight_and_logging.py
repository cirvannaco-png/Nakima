import json
import logging

import pytest

from core.config import PreflightError, Settings, preflight
from core.logging import JsonFormatter


def test_preflight_ok_with_github_token():
    s = Settings(
        DEFAULT_AI_PROVIDER="github",
        GITHUB_TOKEN="x",
        GITHUB_APP_ID=None,
        GITHUB_PRIVATE_KEY=None,
        GITHUB_PRIVATE_KEY_PATH=None,
        GITHUB_WEBHOOK_SECRET="",
    )
    warnings = preflight(s)
    assert any("GitHub App not configured" in w for w in warnings)


def test_preflight_fails_when_provider_missing_token(monkeypatch):
    # pydantic-settings reads env vars with higher priority than None init kwargs.
    # Clear the token env vars so Settings actually sees None for both fields.
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_MODELS_TOKEN", raising=False)
    s = Settings(DEFAULT_AI_PROVIDER="github", GITHUB_TOKEN=None, GITHUB_MODELS_TOKEN=None)
    with pytest.raises(PreflightError):
        preflight(s)


def test_preflight_rejects_partial_github_app():
    s = Settings(
        DEFAULT_AI_PROVIDER="github",
        GITHUB_TOKEN="x",
        GITHUB_APP_ID="1",
        GITHUB_PRIVATE_KEY=None,
        GITHUB_PRIVATE_KEY_PATH=None,
        GITHUB_WEBHOOK_SECRET="",
    )
    with pytest.raises(PreflightError):
        preflight(s)


def test_preflight_production_requires_strong_secrets():
    s = Settings(
        ENVIRONMENT="production",
        DEFAULT_AI_PROVIDER="github",
        GITHUB_TOKEN="x",
        DB_PASSWORD="nakima",
    )
    with pytest.raises(PreflightError):
        preflight(s)


def test_json_formatter_emits_valid_json_with_extras():
    fmt = JsonFormatter()
    rec = logging.LogRecord(
        name="nakima.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    rec.request_id = "abc-123"
    line = fmt.format(rec)
    payload = json.loads(line)
    assert payload["msg"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "nakima.test"
    assert payload["request_id"] == "abc-123"
    assert "ts" in payload


def test_json_formatter_handles_non_serializable_extra():
    fmt = JsonFormatter()
    rec = logging.LogRecord(
        name="x",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="m",
        args=(),
        exc_info=None,
    )
    rec.thing = object()
    payload = json.loads(fmt.format(rec))
    assert "thing" in payload  # coerced to repr, not dropped
