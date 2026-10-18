import httpx
import pytest

from core.config import settings
from providers.implementations.huggingface_endpoint import HuggingFaceEndpointProvider


@pytest.mark.asyncio
async def test_endpoint_request_is_authenticated_and_token_bounded(monkeypatch):
    monkeypatch.setattr(settings, "HUGGINGFACE_ENDPOINT_URL", "https://private.example")
    monkeypatch.setattr(settings, "HUGGINGFACE_API_TOKEN", "hf-test-secret")
    monkeypatch.setattr(settings, "HUGGINGFACE_MODEL", "test/model")
    monkeypatch.setattr(settings, "HUGGINGFACE_MAX_COMPLETION_TOKENS", 128)
    monkeypatch.setattr(settings, "HUGGINGFACE_MAX_PROMPT_CHARS", 4000)
    monkeypatch.setattr(settings, "HUGGINGFACE_TIMEOUT_SECONDS", 12)
    monkeypatch.setattr(settings, "HUGGINGFACE_FALLBACK_PROVIDER", "")

    captured = {}

    class MockResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "model": "test/model",
                "choices": [{"message": {"content": "No actionable defect found."}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 8},
            }

    class MockClient:
        def __init__(self, *args, **kwargs):
            captured["timeout"] = kwargs["timeout"]
            captured["follow_redirects"] = kwargs["follow_redirects"]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, headers=None, json=None):
            captured.update(url=url, headers=headers, json=json)
            return MockResponse()

    monkeypatch.setattr(httpx, "AsyncClient", MockClient)
    provider = HuggingFaceEndpointProvider()
    response = await provider._call(
        "inspect this snippet",
        max_tokens=8192,
        fallback_method="analyze",
        fallback_args=("inspect this snippet", {}),
    )

    assert response.content == "No actionable defect found."
    assert captured["url"] == "https://private.example/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer hf-test-secret"
    assert captured["json"]["model"] == "test/model"
    assert captured["json"]["max_tokens"] == 128
    assert captured["follow_redirects"] is False


@pytest.mark.asyncio
async def test_prompt_size_limit_falls_back_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "HUGGINGFACE_ENDPOINT_URL", "https://private.example")
    monkeypatch.setattr(settings, "HUGGINGFACE_API_TOKEN", "hf-test-secret")
    monkeypatch.setattr(settings, "HUGGINGFACE_MAX_PROMPT_CHARS", 1000)
    monkeypatch.setattr(settings, "HUGGINGFACE_FALLBACK_PROVIDER", "github")

    class Fallback:
        async def analyze(self, code, context):
            from providers.base import ProviderResponse
            return ProviderResponse(content="fallback result", model="mock-fallback")

    class Manager:
        def get_provider(self, name):
            assert name == "github"
            return Fallback()

    import providers.manager as manager_module
    monkeypatch.setattr(manager_module, "provider_manager", Manager())

    provider = HuggingFaceEndpointProvider()
    result = await provider.analyze("x" * 1500, {})
    assert result.content == "fallback result"
    assert result.model == "mock-fallback"


@pytest.mark.asyncio
async def test_missing_credentials_fails_closed_without_fallback(monkeypatch):
    monkeypatch.setattr(settings, "HUGGINGFACE_ENDPOINT_URL", None)
    monkeypatch.setattr(settings, "HUGGINGFACE_API_TOKEN", None)
    monkeypatch.setattr(settings, "HUGGINGFACE_FALLBACK_PROVIDER", "")

    provider = HuggingFaceEndpointProvider()
    with pytest.raises(RuntimeError, match="Hugging Face inference failed"):
        await provider.analyze("print('hello')", {})
