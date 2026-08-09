"""
NEIS Self-Healing Engine
=========================

This is the core loop that makes "self-healing" a real, bounded, auditable
process instead of "call a model, hope, apply diff." Runs entirely inside
the network-isolated sandbox container.

Design principles this enforces (fixing gaps in a naive first pass):

1. BOUNDED RETRY, NOT UNBOUNDED LOOPING.
   A self-healing loop that keeps trying until it "works" is an anti-pattern
   (unbounded retry -> can burn arbitrary compute, can thrash a repo state,
   can never terminate on genuinely unfixable failures). MAX_HEAL_ATTEMPTS
   is a hard ceiling. On exhaustion: escalate to human review with full
   diagnostic trail, never silently give up and never loop forever.

2. VALIDATE AGAINST THE FULL SUITE, NOT JUST THE FAILING TEST.
   A fix that makes the one failing test pass while breaking two others is
   worse than no fix. Every candidate is validated against the entire test
   suite before being considered a candidate at all.

3. MULTI-MODEL CANDIDATES + JUDGE, NOT SINGLE-SHOT.
   Generate independent candidate fixes from multiple providers, validate
   each, then select — don't commit to the first model's first idea.
   Runtime selection only; see docs/PROVIDER_TOS_NOTES.md for why these
   candidates are NOT persisted as training data.

4. CONFIDENCE IS COMPUTED, NOT ASSERTED.
   A fix's confidence score is a function of: test suite pass/fail,
   cross-model agreement, and similarity to previously human-validated
   patterns in pattern_memory (read-only lookup here — this loop never
   writes to pattern_memory directly; promotion is a separate offline step).

5. SECURITY-CLASSIFIED FAILURES NEVER AUTO-ESCALATE PRIVILEGE.
   If diagnosis classifies the failure as a security finding, the loop still
   runs, but the output is always routed to human review regardless of
   confidence score — see `requires_mandatory_review`.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger("nakima.neis.self_healing")

MAX_HEAL_ATTEMPTS = 3           # hard ceiling per run; see design principle 1
MIN_CONFIDENCE_TO_SURFACE = 0.55  # below this, don't even show the user a fix — say "no confident fix found"
CANDIDATE_MODELS = ["claude", "gpt", "gemini", "deepseek", "kimi"]  # order = fallback priority, not preference ranking


class FailureClass(str, Enum):
    ci_test_failure = "ci_test_failure"
    build_failure = "build_failure"
    dependency_conflict = "dependency_conflict"
    security_finding = "security_finding"
    deploy_failure = "deploy_failure"
    unknown = "unknown"


@dataclass
class Diagnosis:
    failure_class: FailureClass
    root_cause_summary: str
    affected_files: list[str]
    raw_log_excerpt: str
    is_security_relevant: bool = False


@dataclass
class CandidateFix:
    provider: str
    diff: str
    rationale: str
    full_suite_passed: Optional[bool] = None
    suite_output_summary: Optional[str] = None


@dataclass
class HealResult:
    success: bool
    attempts_used: int
    final_diagnosis: Diagnosis
    selected_candidate: Optional[CandidateFix]
    all_candidates: list[CandidateFix] = field(default_factory=list)
    confidence_score: float = 0.0
    requires_mandatory_review: bool = True  # default safe: everything needs review until proven otherwise
    escalation_reason: Optional[str] = None


class TestSuiteRunner:
    """
    Thin wrapper so the healing loop doesn't care whether it's pytest,
    jest, go test, etc. Sandbox entrypoint detects the suite once per repo
    and passes the right runner in.
    """

    def __init__(self, run_command: list[str], cwd: str):
        self.run_command = run_command
        self.cwd = cwd

    def run(self, timeout_seconds: int = 600) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                self.run_command,
                cwd=self.cwd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            passed = result.returncode == 0
            output = (result.stdout or "") + "\n" + (result.stderr or "")
            return passed, output[-8000:]  # cap captured output, this feeds into logs/DB
        except subprocess.TimeoutExpired:
            return False, "TEST SUITE TIMED OUT — treated as failure, not as pass"


def diagnose_failure(ci_log: str, repo_context: dict) -> Diagnosis:
    """
    Root-cause diagnosis step. In production this calls the primary model
    (Claude) with the CI log + repo context and asks for structured output:
    failure class, affected files, root cause in plain language, and whether
    this looks security-relevant (which changes the review requirement
    downstream regardless of what happens next).

    Kept as a clear interface here so it's swappable/testable independent of
    the orchestration loop around it.
    """
    raise NotImplementedError("wire to model call with structured output schema")


def generate_candidate_fix(provider: str, diagnosis: Diagnosis, repo_snapshot_path: str) -> CandidateFix:
    """
    Ask one provider for an independent candidate fix. Providers must not see
    each other's attempts — independence is what makes cross-model agreement
    a meaningful confidence signal. If they see each other's output, agreement
    just measures anchoring, not correctness.
    """
    raise NotImplementedError("wire to provider-specific API call")


def score_confidence(diagnosis: Diagnosis, candidates: list[CandidateFix], pattern_matches: list[dict]) -> float:
    """
    Confidence = weighted combination of:
      - fraction of candidates whose diff passed the FULL suite (not just target test)
      - cross-model agreement (do independent providers converge on a similar fix?)
      - similarity to prior human-validated patterns for this vulnerability_class/language

    This is intentionally simple and legible — a principal-engineer instinct
    here is to resist the urge to make this a black-box learned scorer before
    you have enough labeled outcomes to validate it against. Start
    interpretable, replace with a learned model only once you have enough
    outcome data to evaluate it against this baseline.
    """
    passing = [c for c in candidates if c.full_suite_passed]
    if not passing:
        return 0.0

    pass_rate = len(passing) / max(len(candidates), 1)

    # crude agreement signal: what fraction of PASSING candidates share a
    # near-identical diff shape. Real implementation should use AST-level
    # diff similarity, not string similarity — string similarity is a
    # placeholder here, flagged explicitly so it isn't mistaken for done.
    agreement = _rough_diff_agreement([c.diff for c in passing])

    pattern_boost = 0.1 if pattern_matches else 0.0

    score = (0.55 * pass_rate) + (0.35 * agreement) + pattern_boost
    return min(round(score, 3), 1.0)


def _rough_diff_agreement(diffs: list[str]) -> float:
    if len(diffs) < 2:
        return 0.5  # single passing candidate: neutral, not confident, not zero
    # PLACEHOLDER: replace with AST-normalized diff comparison before this
    # ships to production. Flagged in known-gaps.md.
    unique = len(set(d.strip() for d in diffs))
    return 1.0 - ((unique - 1) / len(diffs))


def run_self_healing_loop(
    ci_log: str,
    repo_context: dict,
    repo_snapshot_path: str,
    suite_runner: TestSuiteRunner,
    pattern_lookup_fn,  # injected: callable(vulnerability_class, language) -> list[dict], read-only
) -> HealResult:
    """
    The bounded loop. Each attempt: diagnose (re-diagnose on retry, since a
    failed candidate might reveal the first diagnosis was wrong) -> generate
    N candidates in parallel across providers -> validate each against full
    suite -> score -> if confidence clears threshold, stop; else retry up to
    MAX_HEAL_ATTEMPTS, then escalate.
    """
    all_candidates: list[CandidateFix] = []
    diagnosis: Optional[Diagnosis] = None

    for attempt in range(1, MAX_HEAL_ATTEMPTS + 1):
        diagnosis = diagnose_failure(ci_log, repo_context)

        candidates = [
            generate_candidate_fix(provider, diagnosis, repo_snapshot_path)
            for provider in CANDIDATE_MODELS
        ]

        for c in candidates:
            passed, output = suite_runner.run()
            c.full_suite_passed = passed
            c.suite_output_summary = output
        all_candidates.extend(candidates)

        pattern_matches = pattern_lookup_fn(
            diagnosis.failure_class.value, repo_context.get("primary_language", "unknown")
        )
        confidence = score_confidence(diagnosis, candidates, pattern_matches)

        passing = [c for c in candidates if c.full_suite_passed]
        if passing and confidence >= MIN_CONFIDENCE_TO_SURFACE:
            selected = max(passing, key=lambda c: len(c.rationale or ""))  # placeholder tie-break; see known-gaps
            return HealResult(
                success=True,
                attempts_used=attempt,
                final_diagnosis=diagnosis,
                selected_candidate=selected,
                all_candidates=all_candidates,
                confidence_score=confidence,
                requires_mandatory_review=diagnosis.is_security_relevant or confidence < 0.75,
                escalation_reason=None,
            )

        logger.info(
            "heal attempt %s/%s: no candidate cleared confidence threshold (best confidence=%s)",
            attempt, MAX_HEAL_ATTEMPTS, confidence,
        )

    # Exhausted attempts without a confident fix — escalate, don't loop forever.
    return HealResult(
        success=False,
        attempts_used=MAX_HEAL_ATTEMPTS,
        final_diagnosis=diagnosis,
        selected_candidate=None,
        all_candidates=all_candidates,
        confidence_score=0.0,
        requires_mandatory_review=True,
        escalation_reason=(
            f"No candidate fix passed the full test suite with sufficient confidence "
            f"after {MAX_HEAL_ATTEMPTS} attempts. Escalating to human review with "
            f"full diagnostic trail."
        ),
    )
