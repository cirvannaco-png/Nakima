"""Hugging Face Inference Endpoint provider.

Uses an authenticated OpenAI-compatible endpoint (for example vLLM-backed
Inference Endpoints). Keep the endpoint private/protected and pin the model
revision in the endpoint configuration. This provider never sends repository
content to a public unauthenticated endpoint.
"""
from typing import Any

import httpx

from core.config import settings
from providers.base import AIProvider, ProviderResponse

FILE_BLOCK_INSTRUCTIONS = """
When you produce code changes, output each file as a separate block in exactly
this format (one block per file, no extra commentary inside the block):

### FILE: relative/path/to/file.py
```
<full file contents>
```
### END FILE

Use "### FILE: path" with DELETE as the entire body to indicate a file should
be deleted. Do not omit unchanged parts of a file with "..." — always write
the complete file contents.
""".strip()


class HuggingFaceEndpointProvider(AIProvider):
    """Bounded, authenticated adapter for an OpenAI-compatible HF endpoint."""

    def __init__(self) -> None:
        self.endpoint_url = (settings.HUGGINGFACE_ENDPOINT_URL or "").strip().rstrip("/")
        self.api_token = settings.HUGGINGFACE_API_TOKEN
        self.model = settings.HUGGINGFACE_MODEL
        self.timeout = max(1.0, float(settings.HUGGINGFACE_TIMEOUT_SECONDS))
        self.max_prompt_chars = max(1000, int(settings.HUGGINGFACE_MAX_PROMPT_CHARS))
        self.max_completion_tokens = max(1, int(settings.HUGGINGFACE_MAX_COMPLETION_TOKENS))
        self.fallback_provider = (settings.HUGGINGFACE_FALLBACK_PROVIDER or "").strip().lower()

    async def _call(
        self,
        prompt: str,
        *,
        system: str = "",
        max_tokens: int | None = None,
        fallback_method: str,
        fallback_args: tuple[Any, ...],
    ) -> ProviderResponse:
        try:
            if not self.endpoint_url:
                raise RuntimeError("HUGGINGFACE_ENDPOINT_URL is not configured")
            if not self.api_token:
                raise RuntimeError("HUGGINGFACE_API_TOKEN is not configured")
            if len(prompt) > self.max_prompt_chars:
                raise ValueError(
                    f"Prompt exceeds HUGGINGFACE_MAX_PROMPT_CHARS ({self.max_prompt_chars})"
                )

            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            timeout = httpx.Timeout(self.timeout, connect=min(10.0, self.timeout))
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                response = await client.post(
                    f"{self.endpoint_url}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_token}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": messages,
                        "max_tokens": min(
                            max_tokens or self.max_completion_tokens,
                            self.max_completion_tokens,
                        ),
                        "temperature": 0,
                    },
                )
                response.raise_for_status()
                data = response.json()

            choices = data.get("choices") or []
            message = (choices[0].get("message") or {}) if choices else {}
            result_text = message.get("content", "") or ""
            if not result_text:
                raise RuntimeError("Hugging Face endpoint returned an empty completion")
            return ProviderResponse(
                content=result_text,
                model=data.get("model", self.model),
                usage=data.get("usage", {}),
            )
        except Exception as exc:
            # Fallback is explicit configuration, never an implicit second paid call.
            if self.fallback_provider and self.fallback_provider != "huggingface":
                try:
                    from providers.manager import provider_manager

                    provider = provider_manager.get_provider(self.fallback_provider)
                    method = getattr(provider, fallback_method)
                    return await method(*fallback_args)
                except Exception as fallback_exc:
                    raise RuntimeError(
                        f"Hugging Face inference failed ({type(exc).__name__}); "
                        f"configured fallback '{self.fallback_provider}' also failed "
                        f"({type(fallback_exc).__name__})"
                    ) from fallback_exc
            raise RuntimeError(f"Hugging Face inference failed: {type(exc).__name__}") from exc

    async def analyze(self, code: str, context: dict[str, Any]) -> ProviderResponse:
        prompt = f"Analyze this code for actionable bugs and security flaws. Distinguish evidence from hypotheses.\n\n{code}\n\nContext: {context}"
        return await self._call(prompt, fallback_method="analyze", fallback_args=(code, context))

    async def plan(self, requirement: str, context: dict[str, Any]) -> ProviderResponse:
        prompt = f"Create a step-by-step implementation plan for this requirement:\n{requirement}\nContext: {context}"
        return await self._call(prompt, fallback_method="plan", fallback_args=(requirement, context))

    async def generate(self, prompt: str, context: dict[str, Any]) -> ProviderResponse:
        full_prompt = f"Generate code changes for: {prompt}\nContext: {context}"
        return await self._call(full_prompt, system=FILE_BLOCK_INSTRUCTIONS, max_tokens=8192,
                                fallback_method="generate", fallback_args=(prompt, context))

    async def debug(self, error: str, context: dict[str, Any]) -> ProviderResponse:
        prompt = f"Debug this error:\n{error}\nContext: {context}"
        return await self._call(prompt, system=FILE_BLOCK_INSTRUCTIONS, max_tokens=8192,
                                fallback_method="debug", fallback_args=(error, context))

    async def review(self, diff: str, context: dict[str, Any]) -> ProviderResponse:
        prompt = f"Review this diff for correctness, security, and regression risk. Cite exact evidence.\n{diff}\nContext: {context}"
        return await self._call(prompt, fallback_method="review", fallback_args=(diff, context))

    async def refactor(self, code: str, instructions: str, context: dict[str, Any]) -> ProviderResponse:
        prompt = f"Refactor this code according to: {instructions}\nCode:\n{code}\nContext: {context}"
        return await self._call(prompt, system=FILE_BLOCK_INSTRUCTIONS, max_tokens=8192,
                                fallback_method="refactor", fallback_args=(code, instructions, context))

    async def explain(self, code: str, context: dict[str, Any]) -> ProviderResponse:
        prompt = f"Explain this code in detail:\n{code}\nContext: {context}"
        return await self._call(prompt, fallback_method="explain", fallback_args=(code, context))

    async def generate_tests(self, code: str, context: dict[str, Any]) -> ProviderResponse:
        prompt = f"Generate focused tests that fail on the described defect and pass on correct behavior:\n{code}\nContext: {context}"
        return await self._call(prompt, system=FILE_BLOCK_INSTRUCTIONS, max_tokens=8192,
                                fallback_method="generate_tests", fallback_args=(code, context))
