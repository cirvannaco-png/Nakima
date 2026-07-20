from unittest.mock import AsyncMock

import pytest

from models.neis.evolution_roadmap import RecommendationCategory
from models.neis.project_reality import ProjectRealityModel
from models.neis.technology_intel import Ecosystem, TechnologyIntel
from models.neis.user_intent import UserIntent
from neis.analyzers.innovation_engine import InnovationReasoningEngine


def _reality(**overrides) -> ProjectRealityModel:
    defaults = dict(
        repository_id=1,
        languages={"python": 5},
        dependencies=[],
        loc_by_language={"python": 500},
        file_count=5,
        test_file_count=0,
        health_score=40.0,
        health_components={"test_to_code_file_ratio": 0.0, "docstring_coverage": 0.1},
    )
    defaults.update(overrides)
    return ProjectRealityModel(**defaults)


def _tech_intel(**overrides) -> TechnologyIntel:
    defaults = dict(
        repository_id=1,
        package_name="fastapi",
        ecosystem=Ecosystem.PYPI,
        current_version="1.0.0",
        latest_version="3.0.0",
        is_outdated=True,
        major_versions_behind=2,
    )
    defaults.update(overrides)
    return TechnologyIntel(**defaults)


async def test_outdated_dependency_produces_recommendation():
    engine = InnovationReasoningEngine()
    recs = engine.generate_recommendations(_reality(health_score=None), [_tech_intel()], [], None)

    dep_recs = [r for r in recs if r["category"] == RecommendationCategory.DEPENDENCY]
    assert len(dep_recs) == 1
    assert "fastapi" in dep_recs[0]["title"]
    assert dep_recs[0]["priority_score"] == pytest.approx(4.0)  # 2 majors behind * 2.0, weight 1.0


async def test_up_to_date_dependency_produces_no_recommendation():
    engine = InnovationReasoningEngine()
    current = _tech_intel(is_outdated=False, major_versions_behind=0, latest_version="1.0.0")
    recs = engine.generate_recommendations(_reality(health_score=None), [current], [], None)
    assert [r for r in recs if r["category"] == RecommendationCategory.DEPENDENCY] == []


async def test_low_health_score_produces_testing_recommendation():
    engine = InnovationReasoningEngine()
    recs = engine.generate_recommendations(_reality(), [], [], None)
    assert any(r["category"] == RecommendationCategory.TESTING for r in recs)


async def test_healthy_repo_produces_no_testing_recommendation():
    engine = InnovationReasoningEngine()
    healthy = _reality(health_score=95.0, health_components={"test_to_code_file_ratio": 0.6, "docstring_coverage": 0.9})
    recs = engine.generate_recommendations(healthy, [], [], None)
    assert [r for r in recs if r["category"] == RecommendationCategory.TESTING] == []


async def test_god_class_pattern_produces_architecture_recommendation():
    engine = InnovationReasoningEngine()
    pattern = {
        "pattern_type": "god_class",
        "subject": "big.py::Everything",
        "summary": "Class Everything has 20 methods",
        "method_count": 20,
        "file_path": "big.py",
    }
    recs = engine.generate_recommendations(_reality(health_score=None), [], [pattern], None)
    arch_recs = [r for r in recs if r["category"] == RecommendationCategory.ARCHITECTURE]
    assert len(arch_recs) == 1
    assert "Everything" in arch_recs[0]["title"]


async def test_priority_weight_scales_recommendation_score():
    engine = InnovationReasoningEngine()
    intent = UserIntent(repository_id=1, goals=[], constraints=[], priority_weights={"dependency": 3.0})
    recs = engine.generate_recommendations(_reality(health_score=None), [_tech_intel()], [], intent)
    assert recs[0]["priority_score"] == pytest.approx(4.0 * 3.0)


async def test_constraint_suppresses_matching_recommendation():
    engine = InnovationReasoningEngine()
    intent = UserIntent(repository_id=1, goals=[], constraints=["fastapi"], priority_weights={})
    recs = engine.generate_recommendations(_reality(health_score=None), [_tech_intel()], [], intent)
    assert recs == []


async def test_summarize_falls_back_when_no_provider():
    engine = InnovationReasoningEngine()
    recs = engine.generate_recommendations(_reality(health_score=None), [_tech_intel()], [], None)
    summary = await engine.summarize(recs, provider=None)
    assert "1 recommendation" in summary


async def test_summarize_falls_back_when_provider_call_fails():
    engine = InnovationReasoningEngine()
    recs = engine.generate_recommendations(_reality(health_score=None), [_tech_intel()], [], None)
    broken_provider = AsyncMock()
    broken_provider.explain.side_effect = RuntimeError("provider down")

    summary = await engine.summarize(recs, provider=broken_provider)
    assert "1 recommendation" in summary  # deterministic fallback, not a raised exception


async def test_summarize_empty_recommendations_uses_fallback_text():
    engine = InnovationReasoningEngine()
    summary = await engine.summarize([], provider=None)
    assert "No recommendations" in summary
