"""Trims a ContextBuilder payload down to a token budget before it goes to
an AIProvider.

ContextBuilder.build_for_task already does one crude form of this —
max_snippet_chars truncates every snippet individually — but that caps
each file the same regardless of relevance, and does nothing to the
dependency_subgraph, which can grow unbounded on a highly-connected file.
On a large repo the combined payload can still blow past what a provider
accepts, and among providers/implementations only claude.py's model has
a context window large enough to shrug that off.

This compressor works on the already-built context dict, not on raw repo
files, so it stays independent of how ContextBuilder assembles things:

  1. Score each snippet by dependency_subgraph fan-in (depended_on_by
     count) — a file many others import is more likely to matter to a
     change than one nobody touches, which is the same signal
     neis/analyzers/pattern_extractor.py uses for high_coupling_file.
  2. Keep snippets highest-score-first until the running token estimate
     would exceed the budget; drop the rest entirely rather than
     truncating everyone equally, since a half-file is often less useful
     than a complete lower-priority file.
  3. requirement is never dropped or truncated — it's the smallest part
     of the payload and losing it makes the rest meaningless.

Token counting is an approximation (chars / 4, the same rule of thumb
OpenAI and Anthropic both publish for English text) rather than a real
tokenizer, because no tokenizer dependency is installed in this repo
(see requirements.txt) and provider responses in providers/base.py don't
expose per-request token counts we could calibrate against. If a real
tokenizer is added later, only _estimate_tokens needs to change.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

CHARS_PER_TOKEN_ESTIMATE = 4


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN_ESTIMATE)


class TokenCompressor:
    def __init__(self, max_tokens: int = 8000):
        self.max_tokens = max_tokens

    def compress(self, context: dict[str, Any]) -> dict[str, Any]:
        requirement = context.get("requirement", "")
        snippets = context.get("code_snippets", [])
        subgraph = context.get("dependency_subgraph", {})

        budget = self.max_tokens - _estimate_tokens(requirement)
        if budget <= 0:
            logger.warning("Token budget exhausted by requirement text alone (%d tokens)", self.max_tokens)
            return {"requirement": requirement, "code_snippets": [], "dependency_subgraph": {}, "compression": {}}

        def fan_in(snippet: dict) -> int:
            edges = subgraph.get(snippet["file"], {})
            return len(edges.get("depended_on_by", []))

        ordered = sorted(snippets, key=fan_in, reverse=True)

        kept: list[dict] = []
        used = 0
        dropped_files: list[str] = []
        for snippet in ordered:
            cost = _estimate_tokens(snippet["content"])
            if used + cost > budget:
                dropped_files.append(snippet["file"])
                continue
            kept.append(snippet)
            used += cost

        kept_files = {s["file"] for s in kept}
        trimmed_subgraph = {f: edges for f, edges in subgraph.items() if f in kept_files}

        if dropped_files:
            logger.info(
                "TokenCompressor dropped %d/%d snippets to stay within %d tokens: %s",
                len(dropped_files),
                len(snippets),
                self.max_tokens,
                dropped_files,
            )

        return {
            "requirement": requirement,
            "code_snippets": kept,
            "dependency_subgraph": trimmed_subgraph,
            "compression": {
                "budget_tokens": self.max_tokens,
                "estimated_tokens_used": used + _estimate_tokens(requirement),
                "snippets_kept": len(kept),
                "snippets_dropped": dropped_files,
            },
        }
