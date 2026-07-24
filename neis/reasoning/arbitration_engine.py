"""Reconciles EvidenceEngine's deterministic checks with CognitiveEngine's
LLM-assisted judgment into one of four verdicts. This is the piece that
keeps "the cognitive engine had an opinion" from ever carrying the same
weight as "the deterministic evidence found a hard rule violation" — a
hard violation always wins; a cognitive judgment is downgraded rather
than trusted outright even at high confidence, because CognitiveEngine
has no way to *prove* its judgment the way EvidenceEngine does.
"""

import enum
from dataclasses import dataclass, field

from neis.reasoning.cognitive_engine import CognitiveAssessment
from neis.reasoning.evidence_engine import IntentConfidenceResult

# A misaligned judgment below this confidence is treated as too uncertain
# to act on differently than "unclear" — still surfaced in the reasoning
# trail, but doesn't change the verdict on its own.
MISALIGNMENT_CONFIDENCE_THRESHOLD = 0.6


class DriftVerdict(str, enum.Enum):
    APPROVE = "approve"
    WARN = "warn"
    REQUEST_CONFIRMATION = "request_confirmation"
    BLOCK = "block"


@dataclass
class ArbitrationResult:
    verdict: DriftVerdict
    reasoning: list[str] = field(default_factory=list)


class ArbitrationEngine:
    def arbitrate(
        self,
        hard_violations: list[str],
        intent_confidence: IntentConfidenceResult,
        cognitive: CognitiveAssessment,
    ) -> ArbitrationResult:
        reasoning: list[str] = []

        # Deterministic evidence always wins, unconditionally, regardless
        # of what the cognitive engine concluded.
        if hard_violations:
            reasoning.append(
                f"Deterministic evidence: proposed change conflicts with explicit constraint(s): "
                f"{', '.join(hard_violations)}."
            )
            return ArbitrationResult(DriftVerdict.BLOCK, reasoning)

        if intent_confidence.is_low_confidence:
            reasoning.append(
                f"Intent confidence is low ({intent_confidence.score:.2f}, threshold is below "
                f"0.40) — missing: {', '.join(intent_confidence.missing) or 'unspecified'}."
            )
            reasoning.append(
                "Neither deterministic evidence nor cognitive judgment can be weighed reliably "
                "against underspecified intent."
            )
            return ArbitrationResult(DriftVerdict.REQUEST_CONFIRMATION, reasoning)

        reasoning.append(f"No hard constraint violations found; intent confidence {intent_confidence.score:.2f}.")
        reasoning.append(
            f"Cognitive assessment ({cognitive.source}): {cognitive.alignment} "
            f"(confidence {cognitive.confidence:.2f}) — {cognitive.explanation}"
        )

        if cognitive.alignment == "misaligned" and cognitive.confidence >= MISALIGNMENT_CONFIDENCE_THRESHOLD:
            reasoning.append(
                "Cognitive engine's misalignment judgment is high-confidence and unopposed by any "
                "deterministic evidence to the contrary — downgraded to WARN rather than BLOCK, "
                "because cognitive judgment alone is never treated as authoritative here."
            )
            return ArbitrationResult(DriftVerdict.WARN, reasoning)

        if cognitive.alignment == "misaligned":
            reasoning.append(
                "Cognitive engine flagged possible misalignment at low confidence — proceeding "
                "with a warning rather than blocking."
            )
            return ArbitrationResult(DriftVerdict.WARN, reasoning)

        if cognitive.alignment == "unclear" and cognitive.source == "fallback":
            reasoning.append("No cognitive judgment available — approving on deterministic evidence alone.")
            return ArbitrationResult(DriftVerdict.APPROVE, reasoning)

        return ArbitrationResult(DriftVerdict.APPROVE, reasoning)
