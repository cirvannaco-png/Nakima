"""Smoke tests for the GitHub Models provider.

Network calls are mocked — we only verify the provider builds the request
correctly and surfaces a clean error when the token is missing.
"""
import os

import httpx
import pytest


@pytest.mark.asyncio
async def test_missing_token_raises():
    # Ensure a clean env for this test only.
    old_token = os.environ.pop("GITHUB_TOKEN", None)
    old_models_token = os.environ.pop("GITHUB_MODELS_TOKEN", None)
    try:
        # Re-import settings with the cleaned env.
        from importlib import reload

        from core import config as config_mod
        reload(config_mod)
        from providers.implementations import github_models as gm_mod
        reload(gm_mod)

        provider = gm_mod.GitHubModelsProvider()
        with pytest.raises(RuntimeError, match="GITHUB_TOKEN"):
            await provider._call("hello")
    finally:
        if old_token is not None:
            os.environ["GITHUB_TOKEN"] = old_token
        if old_models_token is not None:
            os.environ["GITHUB_MODELS_TOKEN"] = old_models_token


@pytest.mark.asyncio
async def test_call_builds_openai_shaped_request(monkeypatch):
    os.environ["GITHUB_TOKEN"] = "ghp-test-token"
    from importlib import reload

    from core import config as config_mod
    reload(config_mod)
    from providers.implementations import github_models as gm_mod
    reload(gm_mod)

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
