"""GitHub Models provider.

GitHub Models (https://github.com/marketplace/models) offers a free-tier,
OpenAI-compatible inference endpoint authenticated with a standard GitHub
personal access token (or the GITHUB_TOKEN issued inside GitHub Actions).
No separate provider account or billing setup is required, which makes it a
good default for open-source projects like Nakima.

Endpoint:  https://models.github.ai/inference/chat/completions
Auth:      Authorization: Bearer <GITHUB_TOKEN>
Docs:      https://docs.github.com/en/github-models/prototyping-with-ai-models
"""

from typing import Any

import httpx

from core.config import settings
from providers.base import AIProvider, ProviderResponse

GITHUB_MODELS_URL = "https://models.github.ai/inference/chat/completions"
DEFAULT_MODEL = "openai/gpt-4o-mini"

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


class GitHubModelsProvider(AIProvider):
    def __init__(self):
        # Prefer the dedicated GITHUB_MODELS_TOKEN if set, otherwise fall
        # back to the standard GITHUB_TOKEN so this works out-of-the-box in
        # GitHub Actions with `permissions: models: read`.
        self.api_key = settings.GITHUB_MODELS_TOKEN or settings.GITHUB_TOKEN
        self.default_model = settings.GITHUB_MODELS_MODEL or DEFAULT_MODEL

    async def _call(self, prompt: str, system: str = "", max_tokens: int = 4096) -> ProviderResponse:
        if not self.api_key:
            raise RuntimeError(
                "GITHUB_TOKEN (or GITHUB_MODELS_TOKEN) is not configured. "
                "Create a fine-grained PAT with the 'Models: read' permission "
                "at https://github.com/settings/personal-access-tokens/new."
            )

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        async with httpx.AsyncClient(timeout=settings.PROVIDER_TIMEOUT) as client:
            resp = await client.post(
                GITHUB_MODELS_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.default_model,
                    "max_tokens": max_tokens,
                    "messages": messages,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        choices = data.get("choices") or []
        text = ""
        if choices:
            text = (choices[0].get("message") or {}).get("content", "") or ""
        return ProviderResponse(
            content=text,
            model=data.get("model", self.default_model),
            usage=data.get("usage", {}),
        )

    async def analyze(self, code: str, context: dict[str, Any]) -> ProviderResponse:
        prompt = f"Analyze this code for bugs, security flaws, and improvements:\n\n{code}\n\nContext: {context}"
        return await self._call(prompt)

    async def plan(self, requirement: str, context: dict[str, Any]) -> ProviderResponse:
        prompt = f"Create a step-by-step implementation plan for this requirement:\n{requirement}\nContext: {context}"
        return await self._call(prompt)

    async def generate(self, prompt: str, context: dict[str, Any]) -> ProviderResponse:
        full_prompt = f"Generate code changes for: {prompt}\nContext: {context}"
        return await self._call(full_prompt, system=FILE_BLOCK_INSTRUCTIONS, max_tokens=8192)

    async def debug(self, error: str, context: dict[str, Any]) -> ProviderResponse:
        prompt = f"Debug this error:\n{error}\nContext: {context}"
        return await self._call(prompt, system=FILE_BLOCK_INSTRUCTIONS, max_tokens=8192)

    async def review(self, diff: str, context: dict[str, Any]) -> ProviderResponse:
        prompt = f"Review this diff for correctness, style, and security:\n{diff}\nContext: {context}"
        return await self._call(prompt)

    async def refactor(self, code: str, instructions: str, context: dict[str, Any]) -> ProviderResponse:
        prompt = f"Refactor this code according to: {instructions}\nCode:\n{code}\nContext: {context}"
        return await self._call(prompt, system=FILE_BLOCK_INSTRUCTIONS, max_tokens=8192)

    async def explain(self, code: str, context: dict[str, Any]) -> ProviderResponse:
        prompt = f"Explain this code in detail:\n{code}"
        return await self._call(prompt)

    async def generate_tests(self, code: str, context: dict[str, Any]) -> ProviderResponse:
        prompt = f"Generate comprehensive unit tests for this code:\n{code}\nContext: {context}"
        return await self._call(prompt, system=FILE_BLOCK_INSTRUCTIONS, max_tokens=8192)
