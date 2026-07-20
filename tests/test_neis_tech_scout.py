from unittest.mock import AsyncMock, patch

import httpx
from sqlalchemy import select

from models.neis.technology_intel import Ecosystem, TechnologyIntel
from models.repository import Repository
from neis.analyzers.tech_scout import TechScout


async def _make_repo(db_session):
    repo = Repository(full_name="kelson/test-repo")
    db_session.add(repo)
    await db_session.commit()
    await db_session.refresh(repo)
    return repo


def _pypi_response(version: str) -> httpx.Response:
    return httpx.Response(200, json={"info": {"version": version}})


def _npm_response(version: str) -> httpx.Response:
    return httpx.Response(200, json={"dist-tags": {"latest": version}})


async def test_outdated_pypi_package_flagged_with_major_gap(db_session):
    repo = await _make_repo(db_session)
    deps = [{"name": "fastapi", "version": "0.100.0", "ecosystem": "pypi"}]

    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=_pypi_response("2.0.0"))):
        results = await TechScout(db_session).scan(repo.id, deps)

    assert len(results) == 1
    assert results[0].is_outdated is True
    assert results[0].major_versions_behind == 2
    assert results[0].latest_version == "2.0.0"
    assert results[0].ecosystem == Ecosystem.PYPI


async def test_current_package_not_flagged_outdated(db_session):
    repo = await _make_repo(db_session)
    deps = [{"name": "fastapi", "version": "1.0.0", "ecosystem": "pypi"}]

    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=_pypi_response("1.0.0"))):
        results = await TechScout(db_session).scan(repo.id, deps)

    assert results[0].is_outdated is False
    assert results[0].major_versions_behind == 0


async def test_npm_package_uses_dist_tags(db_session):
    repo = await _make_repo(db_session)
    deps = [{"name": "react", "version": "17.0.0", "ecosystem": "npm"}]

    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=_npm_response("18.2.0"))):
        results = await TechScout(db_session).scan(repo.id, deps)

    assert results[0].ecosystem == Ecosystem.NPM
    assert results[0].major_versions_behind == 1


async def test_network_failure_degrades_to_unknown_instead_of_raising(db_session):
    repo = await _make_repo(db_session)
    deps = [{"name": "fastapi", "version": "1.0.0", "ecosystem": "pypi"}]

    with patch("httpx.AsyncClient.get", new=AsyncMock(side_effect=httpx.ConnectTimeout("timed out"))):
        results = await TechScout(db_session).scan(repo.id, deps)

    assert len(results) == 1
    assert results[0].latest_version is None
    assert results[0].is_outdated is False  # unknown, not assumed outdated


async def test_package_not_found_upstream_degrades_to_unknown(db_session):
    repo = await _make_repo(db_session)
    deps = [{"name": "totally-made-up-pkg", "version": "1.0.0", "ecosystem": "pypi"}]

    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=httpx.Response(404))):
        results = await TechScout(db_session).scan(repo.id, deps)

    assert results[0].latest_version is None


async def test_non_semver_current_version_does_not_crash(db_session):
    repo = await _make_repo(db_session)
    deps = [{"name": "weird-pkg", "version": "not-a-version", "ecosystem": "pypi"}]

    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=_pypi_response("2.0.0"))):
        results = await TechScout(db_session).scan(repo.id, deps)

    assert results[0].is_outdated is False
    assert results[0].major_versions_behind is None


async def test_rescan_upserts_instead_of_duplicating(db_session):
    repo = await _make_repo(db_session)
    deps = [{"name": "fastapi", "version": "1.0.0", "ecosystem": "pypi"}]

    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=_pypi_response("1.0.0"))):
        await TechScout(db_session).scan(repo.id, deps)

    deps_v2 = [{"name": "fastapi", "version": "1.5.0", "ecosystem": "pypi"}]
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=_pypi_response("2.0.0"))):
        await TechScout(db_session).scan(repo.id, deps_v2)

    rows = (
        (await db_session.execute(select(TechnologyIntel).where(TechnologyIntel.repository_id == repo.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].current_version == "1.5.0"
    assert rows[0].latest_version == "2.0.0"
