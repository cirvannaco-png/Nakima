"""Tests for reports/pdf_generator.py. Generates real PDFs to a tmp_path
and checks the actual file, not a mock — same discipline as the rest of
this test suite.
"""

import pytest

from intelligence.decision_registry import DecisionRegistry
from intelligence.event_log import EventLog
from models.neis.evolution_roadmap import EffortEstimate, EvolutionRoadmap, EvolutionRoadmapItem, RecommendationCategory
from models.neis.project_reality import ProjectRealityModel
from models.neis.user_intent import UserIntent
from models.repository import Repository
from reports.pdf_generator import ReportGenerator


@pytest.fixture(autouse=True)
def _reports_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr("reports.pdf_generator.settings.REPORTS_DIR", str(tmp_path))


async def _make_repo(db_session, full_name="kelson/test-repo"):
    repo = Repository(full_name=full_name)
    db_session.add(repo)
    await db_session.commit()
    await db_session.refresh(repo)
    return repo


def _assert_is_pdf(path):
    with open(path, "rb") as f:
        header = f.read(5)
    assert header == b"%PDF-"


async def test_report_with_no_data_still_produces_a_valid_pdf(db_session):
    repo = await _make_repo(db_session)
    report = await ReportGenerator(db_session, repo.id).generate()

    assert report.version == 1
    _assert_is_pdf(report.file_path)
    # Always-rendered sections, even with nothing behind them.
    assert set(report.sections_included) == {"executive_summary", "intent_alignment"}
    assert "No NEIS analysis has been run yet" in report.executive_summary


async def test_report_includes_sections_with_data(db_session):
    repo = await _make_repo(db_session)

    db_session.add(
        ProjectRealityModel(
            repository_id=repo.id,
            languages={"python": 42},
            dependencies=[{"name": "fastapi", "version": "0.115.0"}],
            loc_by_language={"python": 3800},
            file_count=50,
            test_file_count=12,
            health_score=72.5,
            health_components={"test_to_code_file_ratio": 0.24, "docstring_coverage": 0.4},
        )
    )
    db_session.add(
        UserIntent(
            repository_id=repo.id,
            goals=["reduce startup latency"],
            constraints=["no new dependencies"],
            priority_weights={"security": 2.0},
            notes="A" * 200,
            is_active=True,
        )
    )
    roadmap = EvolutionRoadmap(repository_id=repo.id, summary="2 recommendations generated.")
    db_session.add(roadmap)
    await db_session.flush()
    db_session.add(
        EvolutionRoadmapItem(
            roadmap_id=roadmap.id,
            category=RecommendationCategory.DEPENDENCY,
            title="Upgrade fastapi",
            rationale="one major version behind",
            priority_score=4.0,
            effort_estimate=EffortEstimate.SMALL,
        )
    )
    await db_session.commit()

    await DecisionRegistry(db_session, repo.id).record(
        context="c", problem="p", decision="Reuse existing table", justification="avoids drift"
    )
    await EventLog(db_session, repo.id).record(
        task_description="Fix typo", reason="issue #1", chosen_solution="fixed", verification_status="passed"
    )

    report = await ReportGenerator(db_session, repo.id).generate()

    _assert_is_pdf(report.file_path)
    assert set(report.sections_included) == {
        "executive_summary",
        "project_dna",
        "intent_alignment",
        "engineering_decisions",
        "engineering_timeline",
        "recommendations",
        "technical_debt",
    }
    assert "72.5" in report.executive_summary


async def test_report_version_increments_per_repository(db_session):
    repo = await _make_repo(db_session)
    first = await ReportGenerator(db_session, repo.id).generate()
    second = await ReportGenerator(db_session, repo.id).generate()
    assert first.version == 1
    assert second.version == 2
    assert first.file_path != second.file_path


async def test_report_versions_are_independent_per_repository(db_session):
    repo_a = await _make_repo(db_session, "kelson/repo-a")
    repo_b = await _make_repo(db_session, "kelson/repo-b")
    report_a = await ReportGenerator(db_session, repo_a.id).generate()
    report_b = await ReportGenerator(db_session, repo_b.id).generate()
    assert report_a.version == 1
    assert report_b.version == 1


async def test_generate_raises_for_unknown_repository(db_session):
    with pytest.raises(ValueError, match="No repository"):
        await ReportGenerator(db_session, 999999).generate()
