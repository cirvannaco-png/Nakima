from typing import Any

import httpx

from core.config import settings
from providers.base import AIProvider, ProviderResponse

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-4-6"

# Instructs the model to emit changes in a machine-parseable format so
# ImplementationAgent can turn a single text response into multiple real
# files on disk, instead of dumping everything into one generic file
# (which is what the original scaffold's ImplementationAgent did).
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


class ClaudeProvider(AIProvider):
    def __init__(self):
        self.api_key = settings.ANTHROPIC_API_KEY
        self.default_model = DEFAULT_MODEL

    async def _call(self, prompt: str, system: str = "", max_tokens: int = 4096) -> ProviderResponse:
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not configured")

        async with httpx.AsyncClient(timeout=settings.PROVIDER_TIMEOUT) as client:
            resp = await client.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": ANTHROPIC_VERSION,
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.default_model,
                    "max_tokens": max_tokens,
                    "system": system,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            data = resp.json()

        text = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
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
