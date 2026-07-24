"""Tests for neis/reasoning/. CognitiveEngine and DecisionEngine tests
exercise the no-provider fallback path only — no real network calls,
consistent with how neis/services/evolution_service.py already treats
provider_manager.get_provider() as something that can legitimately fail
or be absent.
"""

from datetime import datetime, timedelta

import pytest

from models.neis.project_reality import ProjectRealityModel
from models.neis.user_intent import UserIntent
from models.repository import Repository
from models.task import Task  # noqa: F401 — resolves Repository's string-based relationship("Task")
from neis.reasoning.arbitration_engine import ArbitrationEngine, DriftVerdict
from neis.reasoning.cognitive_engine import CognitiveAssessment, CognitiveEngine
from neis.reasoning.decision_engine import DecisionEngine
from neis.reasoning.evidence_engine import EvidenceEngine

# ---------------------------------------------------------------------------
# EvidenceEngine
# ---------------------------------------------------------------------------


def _intent(**overrides) -> UserIntent:
    defaults = dict(
        repository_id=1,
        goals=["reduce startup latency", "prepare for a public API", "cut build time"],
        constraints=["no new dependencies", "keep Python 3.11 compatibility", "no breaking API changes"],
        priority_weights={"security": 2.0},
        notes="A" * 200,
        is_active=True,
        created_at=datetime.utcnow(),
    )
    defaults.update(overrides)
    return UserIntent(**defaults)


def test_intent_confidence_full_marks_a_complete_intent_high():
    result = EvidenceEngine().score_intent_confidence(_intent())
    assert result.score == pytest.approx(1.0, abs=0.01)
    assert result.is_low_confidence is False
    assert result.missing == []


def test_intent_confidence_none_is_zero_and_low():
    result = EvidenceEngine().score_intent_confidence(None)
    assert result.score == 0.0
    assert result.is_low_confidence is True
    assert "no UserIntent" in result.missing[0]


def test_intent_confidence_penalizes_missing_fields():
    sparse = _intent(goals=[], constraints=[], priority_weights={}, notes=None)
    result = EvidenceEngine().score_intent_confidence(sparse)
    assert result.score < 0.15  # only freshness credit remains
    assert set(result.missing) >= {"goals", "constraints", "priority_weights", "notes"}


def test_intent_confidence_decays_with_staleness():
    stale = _intent(created_at=datetime.utcnow() - timedelta(days=200))
    fresh_score = EvidenceEngine().score_intent_confidence(_intent()).score
    stale_score = EvidenceEngine().score_intent_confidence(stale).score
    assert stale_score < fresh_score


def test_hard_constraint_violation_detected_by_substring_match():
    intent = _intent(constraints=["no new dependencies"])
    proposed = {"title": "Add redis", "description": "Introduces no new dependencies concerns, see #12"}
    violations = EvidenceEngine().check_hard_constraints(proposed, intent)
    assert violations == ["no new dependencies"]


def test_hard_constraint_no_match_returns_empty():
    intent = _intent(constraints=["no new dependencies"])
    proposed = {"title": "Fix typo", "description": "Corrects a README link"}
    assert EvidenceEngine().check_hard_constraints(proposed, intent) == []


def test_hard_constraint_with_no_intent_returns_empty():
    assert EvidenceEngine().check_hard_constraints({"title": "x"}, None) == []


# ---------------------------------------------------------------------------
# CognitiveEngine (fallback path — no provider)
# ---------------------------------------------------------------------------


async def test_cognitive_engine_falls_back_without_provider():
    result = await CognitiveEngine().assess_alignment({"title": "x"}, None, None, provider=None)
    assert result.alignment == "unclear"
    assert result.confidence == 0.0
    assert result.source == "fallback"


def test_cognitive_engine_parses_well_formed_response():
    text = "ALIGNMENT: misaligned\nCONFIDENCE: 0.85\nEXPLANATION: Adds a queue nobody asked for."
    parsed = CognitiveEngine()._parse_response(text)
    assert parsed.alignment == "misaligned"
    assert parsed.confidence == 0.85
    assert "queue" in parsed.explanation


def test_cognitive_engine_degrades_gracefully_on_malformed_response():
    parsed = CognitiveEngine()._parse_response("not the format I asked for at all")
    assert parsed.alignment == "unclear"
    assert parsed.confidence == 0.0


# ---------------------------------------------------------------------------
# ArbitrationEngine
# ---------------------------------------------------------------------------


def _confidence(score: float, low: bool, missing=None):
    from neis.reasoning.evidence_engine import IntentConfidenceResult

    return IntentConfidenceResult(score=score, components={}, is_low_confidence=low, missing=missing or [])


def test_arbitration_hard_violation_always_blocks_even_with_aligned_cognitive():
    cognitive = CognitiveAssessment(alignment="aligned", confidence=0.99, explanation="looks fine", source="llm")
    result = ArbitrationEngine().arbitrate(["no new dependencies"], _confidence(0.9, False), cognitive)
    assert result.verdict == DriftVerdict.BLOCK


def test_arbitration_low_confidence_requests_confirmation():
    cognitive = CognitiveAssessment(alignment="aligned", confidence=0.9, explanation="fine", source="llm")
    result = ArbitrationEngine().arbitrate([], _confidence(0.1, True, missing=["goals"]), cognitive)
    assert result.verdict == DriftVerdict.REQUEST_CONFIRMATION


def test_arbitration_high_confidence_misalignment_warns_not_blocks():
    cognitive = CognitiveAssessment(alignment="misaligned", confidence=0.8, explanation="scope creep", source="llm")
    result = ArbitrationEngine().arbitrate([], _confidence(0.9, False), cognitive)
    assert result.verdict == DriftVerdict.WARN


def test_arbitration_low_confidence_misalignment_still_warns():
    cognitive = CognitiveAssessment(alignment="misaligned", confidence=0.2, explanation="maybe?", source="llm")
    result = ArbitrationEngine().arbitrate([], _confidence(0.9, False), cognitive)
    assert result.verdict == DriftVerdict.WARN


def test_arbitration_no_provider_approves_on_evidence_alone():
    cognitive = CognitiveAssessment(alignment="unclear", confidence=0.0, explanation="no provider", source="fallback")
    result = ArbitrationEngine().arbitrate([], _confidence(0.9, False), cognitive)
    assert result.verdict == DriftVerdict.APPROVE


def test_arbitration_aligned_approves():
    cognitive = CognitiveAssessment(alignment="aligned", confidence=0.9, explanation="matches goals", source="llm")
    result = ArbitrationEngine().arbitrate([], _confidence(0.9, False), cognitive)
    assert result.verdict == DriftVerdict.APPROVE


# ---------------------------------------------------------------------------
# DecisionEngine (integration, real DB, no provider configured)
# ---------------------------------------------------------------------------


async def _make_repo(db_session):
    repo = Repository(full_name="kelson/test-repo")
    db_session.add(repo)
    await db_session.commit()
    await db_session.refresh(repo)
    return repo


async def test_decision_engine_blocks_on_hard_constraint_violation(db_session, monkeypatch):
    monkeypatch.setattr(
        "neis.reasoning.decision_engine.provider_manager.get_provider",
        lambda *a, **kw: (_ for _ in ()).throw(ValueError("no provider configured in tests")),
    )
    repo = await _make_repo(db_session)
    db_session.add(_intent(repository_id=repo.id, constraints=["no new dependencies"]))
    await db_session.commit()

    result = await DecisionEngine(db_session, repo.id).validate(
        {"title": "Add redis", "description": "no new dependencies here", "affected_files": [], "steps": "add redis"}
    )
    assert result.verdict == DriftVerdict.BLOCK


async def test_decision_engine_requests_confirmation_with_no_intent_at_all(db_session, monkeypatch):
    monkeypatch.setattr(
        "neis.reasoning.decision_engine.provider_manager.get_provider",
        lambda *a, **kw: (_ for _ in ()).throw(ValueError("no provider configured in tests")),
    )
    repo = await _make_repo(db_session)

    result = await DecisionEngine(db_session, repo.id).validate(
        {"title": "Fix typo", "description": "d", "affected_files": [], "steps": "s"}
    )
    assert result.verdict == DriftVerdict.REQUEST_CONFIRMATION


async def test_decision_engine_approves_with_complete_intent_and_no_provider(db_session, monkeypatch):
    monkeypatch.setattr(
        "neis.reasoning.decision_engine.provider_manager.get_provider",
        lambda *a, **kw: (_ for _ in ()).throw(ValueError("no provider configured in tests")),
    )
    repo = await _make_repo(db_session)
    db_session.add(_intent(repository_id=repo.id))
    db_session.add(
        ProjectRealityModel(
            repository_id=repo.id,
            languages={"python": 10},
            dependencies=[],
            loc_by_language={"python": 1000},
            file_count=10,
            test_file_count=5,
            health_score=80.0,
            health_components={},
        )
    )
    await db_session.commit()

    result = await DecisionEngine(db_session, repo.id).validate(
        {"title": "Fix typo", "description": "d", "affected_files": [], "steps": "s"}
    )
    assert result.verdict == DriftVerdict.APPROVE
    assert result.intent_confidence.score == pytest.approx(1.0, abs=0.01)
