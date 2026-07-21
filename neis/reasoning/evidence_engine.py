"""Deterministic evidence for Intent Drift Validation. See
neis/reasoning/__init__.py for how this relates to
neis/analyzers/innovation_engine.py's InnovationReasoningEngine.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from models.neis.user_intent import UserIntent

# Below this score, the Arbitration Engine requests confirmation instead
# of trusting a judgment made against underspecified intent — the EIP
# spec's "requests clarification if confidence is too low."
LOW_CONFIDENCE_THRESHOLD = 0.4

# Weights sum to 1.0 at full completeness. Chosen so that goals (the most
# load-bearing field — InnovationReasoningEngine's constraint suppression
# and priority weighting both depend on it) dominate the score, and a
# stale-but-otherwise-complete intent still loses meaningful ground.
_GOALS_WEIGHT = 0.35
_CONSTRAINTS_WEIGHT = 0.25
_PRIORITY_WEIGHTS_WEIGHT = 0.15
_NOTES_WEIGHT = 0.15
_FRESHNESS_WEIGHT = 0.10
_FRESHNESS_GRACE_DAYS = 90
_FRESHNESS_DECAY_DAYS = 180
_NOTES_FULL_CREDIT_CHARS = 200


@dataclass
class IntentConfidenceResult:
    score: float
    components: dict[str, float]
    is_low_confidence: bool
    missing: list[str] = field(default_factory=list)


class EvidenceEngine:
    def score_intent_confidence(self, intent: UserIntent | None) -> IntentConfidenceResult:
        """How well-specified is this repo's stated intent? Every
        component is a fact about the UserIntent row, not a judgment —
        the same intent always scores the same.
        """
        if intent is None:
            return IntentConfidenceResult(
                score=0.0,
                components={},
                is_low_confidence=True,
                missing=["no UserIntent recorded for this repository"],
            )

        components: dict[str, float] = {}
        missing: list[str] = []

        if intent.goals:
            components["goals"] = min(len(intent.goals), 3) / 3 * _GOALS_WEIGHT
        else:
            components["goals"] = 0.0
            missing.append("goals")

        if intent.constraints:
            components["constraints"] = min(len(intent.constraints), 3) / 3 * _CONSTRAINTS_WEIGHT
        else:
            components["constraints"] = 0.0
            missing.append("constraints")

        if intent.priority_weights:
            components["priority_weights"] = _PRIORITY_WEIGHTS_WEIGHT
        else:
            components["priority_weights"] = 0.0
            missing.append("priority_weights")

        note_len = len(intent.notes or "")
        components["notes"] = min(note_len, _NOTES_FULL_CREDIT_CHARS) / _NOTES_FULL_CREDIT_CHARS * _NOTES_WEIGHT
        if note_len == 0:
            missing.append("notes")

        age_days = (datetime.now(timezone.utc).replace(tzinfo=None) - intent.created_at).days
        if age_days <= _FRESHNESS_GRACE_DAYS:
            components["freshness"] = _FRESHNESS_WEIGHT
        else:
            decay = max(0.0, 1 - (age_days - _FRESHNESS_GRACE_DAYS) / _FRESHNESS_DECAY_DAYS)
            components["freshness"] = _FRESHNESS_WEIGHT * decay
            missing.append(f"intent last set {age_days} days ago — consider refreshing")

        score = round(sum(components.values()), 3)
        return IntentConfidenceResult(
            score=score,
            components=components,
            is_low_confidence=score < LOW_CONFIDENCE_THRESHOLD,
            missing=missing,
        )

    def check_hard_constraints(self, proposed_change: dict, intent: UserIntent | None) -> list[str]:
        """Same substring-match heuristic InnovationReasoningEngine uses
        to suppress recommendations (see its `_suppressed_by_constraint`)
        — a heuristic, not NLP. False negatives (a constraint phrased
        differently than the plan text) are expected; this catches the
        case where a constraint's own wording shows up in what's about to
        change, not the general case of intent-violating changes — that
        general case is CognitiveEngine's job, and its output is
        advisory, not a hard block, precisely because it isn't this
        reliable.
        """
        if not intent or not intent.constraints:
            return []
        haystack = " ".join(
            [
                proposed_change.get("title", ""),
                proposed_change.get("description", ""),
                " ".join(proposed_change.get("affected_files", []) or []),
                str(proposed_change.get("steps", "")),
            ]
        ).lower()
        return [c for c in intent.constraints if c and c.lower() in haystack]
