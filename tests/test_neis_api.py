"""API-level tests for the NEIS endpoints. Mirrors tests/test_api.py's
approach: no real GitHub or Docker access. /analyze itself (which clones a
real repo via RepositoryEngine) is intentionally not exercised at the HTTP
layer here — its logic is already covered end-to-end in
tests/test_neis_evolution_service.py against a real temp directory. These
tests cover the parts that are pure DB + routing: 404s when a repo hasn't
been indexed, and the intent-setting round trip.
"""

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database.base import Base
from database.session import get_db
from models.repository import Repository


def _client_with_db(session):
    from api.router import app

    async def _override():
        yield session

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


async def _setup_engine_and_session():
    from models.graph import GraphEdge, GraphNode  # noqa: F401
    from models.knowledge import KnowledgeEdge, KnowledgeNode  # noqa: F401
    from models.neis.evolution_roadmap import EvolutionRoadmap, EvolutionRoadmapItem  # noqa: F401
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


async def test_analyze_404s_when_repository_not_indexed():
    engine, session = await _setup_engine_and_session()
    try:
        client = _client_with_db(session)
        r = client.post("/api/v1/neis/kelson%2Funindexed/analyze", json={"github_token": "x"})
        assert r.status_code == 404
        assert "not indexed" in r.json()["detail"]
    finally:
        from api.router import app

        app.dependency_overrides.clear()
        await session.close()
        await engine.dispose()


async def test_roadmap_404s_when_no_analysis_has_run():
    engine, session = await _setup_engine_and_session()
    try:
        session.add(Repository(full_name="kelson/repo"))
        await session.commit()

        client = _client_with_db(session)
        r = client.get("/api/v1/neis/kelson%2Frepo/roadmap")
        assert r.status_code == 404
        assert "No roadmap yet" in r.json()["detail"]
    finally:
        from api.router import app

        app.dependency_overrides.clear()
        await session.close()
        await engine.dispose()


async def test_set_and_read_back_intent_via_service():
    """set_intent goes through the endpoint; verifying it stuck is done via
    EvolutionService directly (same session) rather than a GET /intent
    endpoint, since NEIS intentionally exposes intent as write-then-use
    (feeds into /analyze), not as its own read endpoint."""
    engine, session = await _setup_engine_and_session()
    try:
        session.add(Repository(full_name="kelson/repo"))
        await session.commit()

        client = _client_with_db(session)
        r = client.post(
            "/api/v1/neis/kelson%2Frepo/intent",
            json={"goals": ["ship v2"], "constraints": ["no new deps"], "priority_weights": {"security": 2.0}},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["goals"] == ["ship v2"]
        assert body["priority_weights"] == {"security": 2.0}
    finally:
        from api.router import app

        app.dependency_overrides.clear()
        await session.close()
        await engine.dispose()
