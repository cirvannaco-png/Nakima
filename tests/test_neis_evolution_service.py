"""End-to-end test of EvolutionService against a real temp repo and a real
in-memory DB, with only the network boundary (TechScout's PyPI/npm calls)
mocked. Everything else — GraphBuilder, ProjectModeler, PatternExtractor,
InnovationReasoningEngine, RoadmapGenerator — runs for real. This is the
test that would have caught the original NEIS draft's core defect: five
analyzer classes that were never actually wired to run together.
"""

from unittest.mock import AsyncMock, patch

import httpx

from models.neis.evolution_roadmap import RoadmapStatus
from models.repository import Repository
from neis.analyzers.pattern_extractor import GOD_CLASS_METHOD_THRESHOLD
from neis.services.evolution_service import EvolutionService
from repository.graph_builder import GraphBuilder


async def _make_repo(db_session):
    repo = Repository(full_name="kelson/test-repo")
    db_session.add(repo)
    await db_session.commit()
    await db_session.refresh(repo)
    return repo


def _pypi_response(version: str) -> httpx.Response:
    return httpx.Response(200, json={"info": {"version": version}})


async def test_full_pipeline_runs_and_produces_a_roadmap(db_session, tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi==0.100.0\n")
    methods = "\n".join(f"    def method_{i}(self):\n        pass\n" for i in range(GOD_CLASS_METHOD_THRESHOLD + 1))
    (tmp_path / "big.py").write_text(f"class Everything:\n{methods}")

    repo = await _make_repo(db_session)
    await GraphBuilder(tmp_path, repo.id, db_session).build_full_graph()

    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=_pypi_response("2.0.0"))):
        result = await EvolutionService(db_session).run_analysis(tmp_path, repo.id)

    assert result["stages_completed"] == ["project_modeler", "tech_scout", "pattern_extractor", "roadmap_generator"]
    assert result["stages_failed"] == {}
    assert result["recommendation_count"] >= 2  # at least the outdated dep + the god class

    roadmap = await EvolutionService(db_session).get_latest_roadmap(repo.id)
    assert roadmap.status == RoadmapStatus.ACTIVE
    categories = {item.category.value for item in roadmap.items}
    assert "dependency" in categories
    assert "architecture" in categories


async def test_pipeline_degrades_gracefully_when_tech_scout_network_fails(db_session, tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi==0.100.0\n")

    repo = await _make_repo(db_session)
    await GraphBuilder(tmp_path, repo.id, db_session).build_full_graph()

    with patch("httpx.AsyncClient.get", new=AsyncMock(side_effect=httpx.ConnectTimeout("down"))):
        result = await EvolutionService(db_session).run_analysis(tmp_path, repo.id)

    # tech_scout itself doesn't raise (TechScout.scan degrades per-package),
    # so it still "completes" — this proves the orchestrator's per-stage
    # try/except is defense in depth, not the only thing standing between
    # a flaky registry and a crashed analysis run.
    assert "tech_scout" in result["stages_completed"]
    assert result["stages_failed"] == {}
    # a roadmap still gets built even though nothing was flagged outdated
    roadmap = await EvolutionService(db_session).get_latest_roadmap(repo.id)
    assert roadmap is not None


async def test_second_run_supersedes_first_roadmap(db_session, tmp_path):
    (tmp_path / "sample.py").write_text("x = 1\n")
    repo = await _make_repo(db_session)
    await GraphBuilder(tmp_path, repo.id, db_session).build_full_graph()

    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=httpx.Response(404))):
        first_result = await EvolutionService(db_session).run_analysis(tmp_path, repo.id)
        second_result = await EvolutionService(db_session).run_analysis(tmp_path, repo.id)

    assert first_result["roadmap_id"] != second_result["roadmap_id"]
    latest = await EvolutionService(db_session).get_latest_roadmap(repo.id)
    assert str(latest.id) == str(second_result["roadmap_id"])


async def test_user_intent_suppresses_recommendations_end_to_end(db_session, tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi==0.100.0\n")
    repo = await _make_repo(db_session)
    await GraphBuilder(tmp_path, repo.id, db_session).build_full_graph()

    await EvolutionService(db_session).set_intent(
        repo.id, goals=["stability"], constraints=["fastapi"], priority_weights={}, notes=None
    )

    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=_pypi_response("2.0.0"))):
        result = await EvolutionService(db_session).run_analysis(tmp_path, repo.id)

    roadmap = await EvolutionService(db_session).get_latest_roadmap(repo.id)
    assert not any("fastapi" in item.title.lower() for item in roadmap.items)
    assert result["recommendation_count"] == len(roadmap.items)
