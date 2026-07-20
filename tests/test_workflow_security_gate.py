"""Tests for orchestrator/workflow.py's security_gate_should_block(). This
is the one piece of the Security Gate wiring that's practically unit-
testable — the surrounding _run_pipeline requires mocking clone/plan/
generate/validate/push/PR-creation end to end, which no test in this repo
does for any part of the pipeline yet (a pre-existing gap, not one this
change extends). NSIL's own scan/reconcile/scoring behavior is already
covered by tests/test_security_nsil.py; this file only covers the
block-or-proceed decision that consumes NSIL's result.
"""

from dataclasses import dataclass, field

from orchestrator.workflow import build_verification_summary, security_gate_should_block
from quality.gate import QualityGateResult, QualityVerdict


@dataclass
class _FakeNSILResult:
    score: float = 100.0
    counts_by_severity: dict = field(default_factory=dict)
    total_open: int = 0
    new_finding_count: int = 0
    resolved_finding_count: int = 0


def test_clean_scan_does_not_block():
    assert security_gate_should_block(_FakeNSILResult(counts_by_severity={})) is False


def test_low_medium_high_findings_do_not_block():
    result = _FakeNSILResult(counts_by_severity={"high": 3, "medium": 2, "low": 1})
    assert security_gate_should_block(result) is False


def test_a_single_critical_finding_blocks():
    result = _FakeNSILResult(counts_by_severity={"critical": 1})
    assert security_gate_should_block(result) is True


def test_critical_alongside_other_severities_still_blocks():
    result = _FakeNSILResult(counts_by_severity={"critical": 1, "high": 5, "low": 10})
    assert security_gate_should_block(result) is True


@dataclass
class _FakeDriftResult:
    verdict: object  # a DriftVerdict, kept loosely typed to avoid a hard dependency in this fixture


def test_verification_summary_reports_all_three_gates_clean():
    drift = _FakeDriftResult(verdict=_Verdict("approve"))
    nsil = _FakeNSILResult(score=100.0, counts_by_severity={})
    quality = QualityGateResult(verdict=QualityVerdict.APPROVE, has_test_changes=True)

    summary = build_verification_summary(drift, nsil, quality)

    assert "Intent: approve" in summary
    assert "Security: approved" in summary
    assert "Quality: approve" in summary
    assert "no test file touched" not in summary


def test_verification_summary_surfaces_a_quality_warning():
    drift = _FakeDriftResult(verdict=_Verdict("approve"))
    nsil = _FakeNSILResult(score=100.0, counts_by_severity={})
    quality = QualityGateResult(verdict=QualityVerdict.WARN, has_test_changes=False)

    summary = build_verification_summary(drift, nsil, quality)

    assert "no test files touched" in summary


def test_verification_summary_reflects_a_security_warn_without_blocking():
    drift = _FakeDriftResult(verdict=_Verdict("approve"))
    nsil = _FakeNSILResult(score=88.0, counts_by_severity={"high": 1})
    quality = QualityGateResult(verdict=QualityVerdict.APPROVE, has_test_changes=True)

    summary = build_verification_summary(drift, nsil, quality)

    assert "Security: approved" in summary
    assert "score 88/100" in summary


class _Verdict:
    """Minimal stand-in for DriftVerdict — has a `.value` like the real
    str-enum does, without importing neis.reasoning just for a fixture.
    """

    def __init__(self, value: str):
        self.value = value
