"""Tests for the NEIS human review gate: PATCH
/api/v1/neis/{repo}/roadmap/items/{item_id} and the two EvolutionService
methods behind it.

The GitHub boundary is mocked the same way tests/test_neis_api.py mocks
everything network-facing — no real PAT, no real issue is ever opened.
"""

import uuid
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database.base import Base
from database.session import get_db
from models.neis.evolution_roadmap import (
    EffortEstimate,
    EvolutionRoadmap,
    EvolutionRoadmapItem,
    ItemStatus,
    RecommendationCategory,
)
from models.repository import Repository
from neis.services.evolution_service import EvolutionService


def _client_with_db(session):
    from api.router import app

    async def _override():
        yield session

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


async def _setup_engine_and_session():
    from models.graph import GraphEdge, GraphNode  # noqa: F401
    from models.knowledge import KnowledgeEdge, KnowledgeNode  # noqa: F401
    from models.neis.project_reality import ProjectRealityModel  # noqa: F401
    from models.neis.technology_intel import TechnologyIntel  # noqa: F401
    from models.neis.user_intent import UserIntent  # noqa: F401
    from models.policy import RepositoryPolicy  # noqa: F401
    from models.task import Task  # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    return engine, Session()


async def _seed_item(session, repo_full_name="kelson/repo"):
    repo = Repository(full_name=repo_full_name)
    session.add(repo)
    await session.commit()
    await session.refresh(repo)

    roadmap = EvolutionRoadmap(repository_id=repo.id, summary="s")
    session.add(roadmap)
    await session.commit()
    await session.refresh(roadmap)

    item = EvolutionRoadmapItem(
        roadmap_id=roadmap.id,
        category=RecommendationCategory.ARCHITECTURE,
        title="Split the god class",
        rationale="It has too many methods.",
        priority_score=3.5,
        effort_estimate=EffortEstimate.MEDIUM,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return repo, item


def _fake_github(number=42, url="https://github.com/kelson/repo/issues/42"):
    gh = MagicMock()
    gh.return_value.get_repo.return_value.create_issue.return_value = MagicMock(number=number, html_url=url)
    return gh


# --- service level ---


async def test_update_item_status_writes_the_decision(db_session):
    repo, item = await _seed_item(db_session)

    updated = await EvolutionService(db_session).update_item_status(repo.id, item.id, ItemStatus.ACCEPTED)

    assert updated is not None
    assert updated.status == ItemStatus.ACCEPTED


async def test_update_item_status_refuses_an_item_from_another_repository(db_session):
    repo, item = await _seed_item(db_session)
    other = Repository(full_name="kelson/other")
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)

    assert await EvolutionService(db_session).update_item_status(other.id, item.id, ItemStatus.ACCEPTED) is None


async def test_update_item_status_returns_none_for_an_unknown_item(db_session):
    repo, _ = await _seed_item(db_session)

    assert await EvolutionService(db_session).update_item_status(repo.id, uuid.uuid4(), ItemStatus.ACCEPTED) is None


async def test_attach_issue_records_number_and_url(db_session):
    _, item = await _seed_item(db_session)

    updated = await EvolutionService(db_session).attach_issue(item, 7, "https://example.test/7")

    assert updated.issue_number == 7
    assert updated.issue_url == "https://example.test/7"


# --- endpoint level ---


async def test_accepting_with_a_token_opens_an_issue():
    engine, session = await _setup_engine_and_session()
    try:
        _, item = await _seed_item(session)
        client = _client_with_db(session)

        with patch("api.v1.endpoints.neis.Github", _fake_github()):
            r = client.patch(
                f"/api/v1/neis/kelson%2Frepo/roadmap/items/{item.id}",
                json={"status": "accepted", "github_token": "ghp-test"},
            )

        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "accepted"
        assert body["issue_url"] == "https://github.com/kelson/repo/issues/42"
    finally:
        from api.router import app

        app.dependency_overrides.clear()
        await session.close()
        await engine.dispose()


async def test_accepting_twice_does_not_open_a_duplicate_issue():
    engine, session = await _setup_engine_and_session()
    try:
        _, item = await _seed_item(session)
        client = _client_with_db(session)
        gh = _fake_github()

        with patch("api.v1.endpoints.neis.Github", gh):
            client.patch(
                f"/api/v1/neis/kelson%2Frepo/roadmap/items/{item.id}",
                json={"status": "accepted", "github_token": "ghp-test"},
            )
            r = client.patch(
                f"/api/v1/neis/kelson%2Frepo/roadmap/items/{item.id}",
                json={"status": "accepted", "github_token": "ghp-test"},
            )

        assert r.status_code == 200
        assert gh.return_value.get_repo.return_value.create_issue.call_count == 1
        assert r.json()["issue_url"] == "https://github.com/kelson/repo/issues/42"
    finally:
        from api.router import app

        app.dependency_overrides.clear()
        await session.close()
        await engine.dispose()


async def test_dismissing_never_touches_github():
    engine, session = await _setup_engine_and_session()
    try:
        _, item = await _seed_item(session)
        client = _client_with_db(session)
        gh = _fake_github()

        with patch("api.v1.endpoints.neis.Github", gh):
            r = client.patch(
                f"/api/v1/neis/kelson%2Frepo/roadmap/items/{item.id}",
                json={"status": "dismissed", "github_token": "ghp-test"},
            )

        assert r.status_code == 200
        assert r.json()["status"] == "dismissed"
        assert r.json()["issue_url"] is None
        gh.return_value.get_repo.assert_not_called()
    finally:
        from api.router import app

        app.dependency_overrides.clear()
        await session.close()
        await engine.dispose()


async def test_issue_creation_failure_still_records_the_decision():
    engine, session = await _setup_engine_and_session()
    try:
        _, item = await _seed_item(session)
        client = _client_with_db(session)
        gh = MagicMock()
        gh.return_value.get_repo.side_effect = RuntimeError("GitHub is down")

        with patch("api.v1.endpoints.neis.Github", gh):
            r = client.patch(
                f"/api/v1/neis/kelson%2Frepo/roadmap/items/{item.id}",
                json={"status": "accepted", "github_token": "ghp-test"},
            )

        assert r.status_code == 200
        assert r.json()["status"] == "accepted"
        assert r.json()["issue_url"] is None
    finally:
        from api.router import app

        app.dependency_overrides.clear()
        await session.close()
        await engine.dispose()


async def test_unknown_item_404s():
    engine, session = await _setup_engine_and_session()
    try:
        await _seed_item(session)
        client = _client_with_db(session)

        r = client.patch(
            f"/api/v1/neis/kelson%2Frepo/roadmap/items/{uuid.uuid4()}",
            json={"status": "accepted"},
        )
        assert r.status_code == 404
        assert "Roadmap item not found" in r.json()["detail"]
    finally:
        from api.router import app

        app.dependency_overrides.clear()
        await session.close()
        await engine.dispose()


async def test_completed_is_not_an_acceptable_target_status():
    engine, session = await _setup_engine_and_session()
    try:
        _, item = await _seed_item(session)
        client = _client_with_db(session)

        r = client.patch(
            f"/api/v1/neis/kelson%2Frepo/roadmap/items/{item.id}",
            json={"status": "completed"},
        )
        assert r.status_code == 422
    finally:
        from api.router import app

        app.dependency_overrides.clear()
        await session.close()
        await engine.dispose()
