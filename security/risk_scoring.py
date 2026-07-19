"""Deterministic Security Risk Scoring — combines finding counts from
SAST, Secret Detection, Configuration Security, and Dependency Audit into
one 0-100 score (100 = clean). Same "same input always produces the same
output" discipline as neis/reasoning/evidence_engine.py. This is a
severity-weighted count, not a judgment call — there's no cognitive
layer here because "how many critical findings exist" isn't a question
with more than one correct answer.
"""

from dataclasses import dataclass, field

# Points deducted per finding, by severity. A single critical finding
# (e.g. a committed AWS key) drops the score further than a stack of low
# findings — intentional, since severity classes aren't linear in actual
# risk. Floors at 0 rather than going negative.
_SEVERITY_WEIGHTS = {
    "critical": 25,
    "high": 12,
    "medium": 5,
    "low": 2,
}


@dataclass
class RiskScore:
    score: float
    counts_by_severity: dict[str, int] = field(default_factory=dict)
    total_findings: int = 0


class RiskScorer:
    def score(self, severities: list[str]) -> RiskScore:
        """`severities` is a flat list of severity strings across every
        finding from every scanner — the caller (SecurityIntelligenceLayer)
        is responsible for gathering them; this class only knows how to
        turn counts into a number.
        """
        counts: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for s in severities:
            counts[s] = counts.get(s, 0) + 1

        deduction = sum(_SEVERITY_WEIGHTS.get(sev, 0) * count for sev, count in counts.items())
        final_score = max(0.0, 100.0 - deduction)

        return RiskScore(score=final_score, counts_by_severity=counts, total_findings=sum(counts.values()))
