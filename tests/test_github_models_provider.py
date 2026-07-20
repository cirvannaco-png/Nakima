"""Smoke tests for the GitHub Models provider.

Network calls are mocked — we only verify the provider builds the request
correctly and surfaces a clean error when the token is missing.

Uses monkeypatch.setattr on the core.config.settings singleton's fields,
not importlib.reload(core.config) — reload() replaces the module's
Settings/PreflightError classes with new objects, so any test module that
imported the old classes earlier in the session (pytest collects all test
modules before running any of them) ends up holding a stale reference that
`isinstance` no longer recognizes, silently breaking `pytest.raises(...)`
in unrelated test files. monkeypatch reverts attribute changes
automatically after each test, so no manual os.environ restoration is
needed either.
"""

import httpx
import pytest

from core.config import settings
from providers.implementations import github_models as gm_mod


@pytest.mark.asyncio
async def test_missing_token_raises(monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_TOKEN", None)
    monkeypatch.setattr(settings, "GITHUB_MODELS_TOKEN", None)

    provider = gm_mod.GitHubModelsProvider()
    with pytest.raises(RuntimeError, match="GITHUB_TOKEN"):
        await provider._call("hello")


@pytest.mark.asyncio
async def test_call_builds_openai_shaped_request(monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_TOKEN", "ghp-test-token")
    monkeypatch.setattr(settings, "GITHUB_MODELS_TOKEN", None)

    captured = {}

    class _MockResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "model": "openai/gpt-4o-mini",
                "choices": [{"message": {"content": "hi from mock"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2},
            }

    class _MockClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return _MockResponse()

    monkeypatch.setattr(httpx, "AsyncClient", _MockClient)

    provider = gm_mod.GitHubModelsProvider()
    resp = await provider._call("hello world", system="be terse")

    assert resp.content == "hi from mock"
    assert captured["url"].endswith("/inference/chat/completions")
    assert captured["headers"]["Authorization"] == "Bearer ghp-test-token"
    assert captured["json"]["messages"][0] == {"role": "system", "content": "be terse"}
    assert captured["json"]["messages"][1] == {"role": "user", "content": "hello world"}
