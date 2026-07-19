"""LLM-assisted judgment for questions EvidenceEngine can't settle by
lookup — "does this planned change fit the project's stated goals?" has
no deterministic answer. Never authoritative alone: ArbitrationEngine
always weighs this against deterministic evidence. See
neis/reasoning/__init__.py.
"""

import logging
from dataclasses import dataclass

from models.neis.project_reality import ProjectRealityModel
from models.neis.user_intent import UserIntent
from providers.base import AIProvider

logger = logging.getLogger(__name__)

VALID_ALIGNMENTS = {"aligned", "unclear", "misaligned"}


@dataclass
class CognitiveAssessment:
    alignment: str  # "aligned" | "unclear" | "misaligned"
    confidence: float  # 0.0-1.0 — the engine's own stated confidence in this judgment
    explanation: str
    source: str  # "llm" | "fallback"


class CognitiveEngine:
    async def assess_alignment(
        self,
        proposed_change: dict,
        intent: UserIntent | None,
        reality: ProjectRealityModel | None,
        provider: AIProvider | None,
    ) -> CognitiveAssessment:
        if not provider:
            return CognitiveAssessment(
                alignment="unclear",
                confidence=0.0,
                explanation="No AI provider configured — cognitive judgment unavailable, "
                "arbitration will rely on deterministic evidence only.",
                source="fallback",
            )

        try:
            plan_description = self._render_plan(proposed_change)
            context = {
                "task": (
                    "You are judging whether a planned code change aligns with this project's stated "
                    "intent. Respond in exactly this format:\nALIGNMENT: aligned|unclear|misaligned\n"
                    "CONFIDENCE: <0.0-1.0>\nEXPLANATION: <one or two sentences>"
                ),
                "goals": (intent.goals if intent else []) or [],
                "constraints": (intent.constraints if intent else []) or [],
                "health_score": reality.health_score if reality else None,
            }
            # Reusing `review` for a pre-generation plan rather than a real
            # diff — same reuse-the-closest-fit-method precedent as
            # InnovationReasoningEngine.summarize() reusing `explain` for a
            # non-code narrative. There's no "review this plan" primitive
            # in providers/base.py and adding one is a larger interface
            # change than this task warrants.
            response = await provider.review(diff=plan_description, context=context)
            return self._parse_response(response.content)
        except Exception as e:
            logger.warning(f"CognitiveEngine.assess_alignment failed, falling back: {e}")
            return CognitiveAssessment(
                alignment="unclear",
                confidence=0.0,
                explanation=f"Cognitive assessment failed ({type(e).__name__}); "
                "arbitration will rely on deterministic evidence only.",
                source="fallback",
            )

    def _render_plan(self, proposed_change: dict) -> str:
        lines = [f"Title: {proposed_change.get('title', '')}"]
        if proposed_change.get("description"):
            lines.append(f"Description: {proposed_change['description']}")
        if proposed_change.get("affected_files"):
            lines.append(f"Affected files: {', '.join(proposed_change['affected_files'])}")
        if proposed_change.get("steps"):
            lines.append(f"Planned steps: {proposed_change['steps']}")
        return "\n".join(lines)

    def _parse_response(self, text: str) -> CognitiveAssessment:
        """Best-effort line-based parse. A malformed or unexpected LLM
        response degrades to an unclear/zero-confidence assessment rather
        than raising — the pipeline must not crash because a model didn't
        follow the requested format.
        """
        alignment = "unclear"
        confidence = 0.0
        explanation = text.strip()[:500] if text else "Empty response from provider."

        for line in (text or "").splitlines():
            line = line.strip()
            if line.upper().startswith("ALIGNMENT:"):
                value = line.split(":", 1)[1].strip().lower()
                if value in VALID_ALIGNMENTS:
                    alignment = value
            elif line.upper().startswith("CONFIDENCE:"):
                try:
                    confidence = max(0.0, min(1.0, float(line.split(":", 1)[1].strip())))
                except ValueError:
                    pass
            elif line.upper().startswith("EXPLANATION:"):
                explanation = line.split(":", 1)[1].strip()

        return CognitiveAssessment(alignment=alignment, confidence=confidence, explanation=explanation, source="llm")
