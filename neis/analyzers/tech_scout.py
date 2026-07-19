"""Checks each dependency a ProjectRealityModel snapshot found against its
real upstream registry (PyPI or npm) and persists the result as
TechnologyIntel. This is the one NEIS component that makes outbound network
calls to systems Nakima doesn't control, so every call is individually
try/excepted — one unreachable or unknown package degrades that package's
intel to "unknown latest version" instead of failing the whole scout run.
This mirrors execution/sandbox.py's SandboxExecutor.network_disabled split:
that module explicitly disables network for anything running generated
code; this one explicitly needs network for a trusted, read-only registry
lookup, and both document why in-line rather than leaving it implicit.
"""

import logging

import httpx
from packaging.version import InvalidVersion, Version
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from models.neis.technology_intel import Ecosystem, TechnologyIntel

logger = logging.getLogger(__name__)

PYPI_URL = "https://pypi.org/pypi/{name}/json"
NPM_URL = "https://registry.npmjs.org/{name}"


class TechScout:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def scan(self, repository_id: int, dependencies: list[dict]) -> list[TechnologyIntel]:
        """`dependencies` is ProjectRealityModel.dependencies —
        [{"name", "version", "ecosystem"}, ...] from the latest snapshot."""
        results: list[TechnologyIntel] = []
        async with httpx.AsyncClient(timeout=settings.NEIS_HTTP_TIMEOUT) as client:
            for dep in dependencies:
                intel = await self._scan_one(client, repository_id, dep)
                if intel:
                    results.append(intel)
        return results

    async def _scan_one(self, client: httpx.AsyncClient, repository_id: int, dep: dict) -> TechnologyIntel | None:
        name, current_version, ecosystem = dep["name"], dep["version"], dep["ecosystem"]
        latest_version = await self._fetch_latest(client, name, ecosystem)

        is_outdated = False
        major_versions_behind = None
        if latest_version:
            is_outdated, major_versions_behind = self._compare(current_version, latest_version)

        existing = (
            (
                await self.session.execute(
                    select(TechnologyIntel).where(
                        TechnologyIntel.repository_id == repository_id,
                        TechnologyIntel.package_name == name,
                        TechnologyIntel.ecosystem == Ecosystem(ecosystem),
                    )
                )
            )
            .scalars()
            .first()
        )

        if existing:
            existing.current_version = current_version
            existing.latest_version = latest_version
            existing.is_outdated = is_outdated
            existing.major_versions_behind = major_versions_behind
            intel = existing
        else:
            intel = TechnologyIntel(
                repository_id=repository_id,
                package_name=name,
                ecosystem=Ecosystem(ecosystem),
                current_version=current_version,
                latest_version=latest_version,
                is_outdated=is_outdated,
                major_versions_behind=major_versions_behind,
            )
            self.session.add(intel)

        await self.session.flush()
        return intel

    async def _fetch_latest(self, client: httpx.AsyncClient, name: str, ecosystem: str) -> str | None:
        url = PYPI_URL.format(name=name) if ecosystem == "pypi" else NPM_URL.format(name=name)
        for attempt in range(settings.NEIS_HTTP_MAX_RETRIES + 1):
            try:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return None  # package not found upstream, or registry error — not worth retrying
                data = resp.json()
                if ecosystem == "pypi":
                    return data.get("info", {}).get("version")
                return data.get("dist-tags", {}).get("latest")
            except (httpx.HTTPError, ValueError) as e:
                if attempt == settings.NEIS_HTTP_MAX_RETRIES:
                    logger.warning(f"tech_scout: failed to resolve {ecosystem}:{name} — {e}")
                    return None
        return None

    def _compare(self, current: str, latest: str) -> tuple[bool, int | None]:
        try:
            current_v, latest_v = Version(current), Version(latest)
        except InvalidVersion:
            # Non-semver version strings (git refs, "*", local build tags)
            # can't be compared meaningfully — report as unknown, not outdated.
            return False, None
        if latest_v <= current_v:
            return False, 0
        return True, latest_v.major - current_v.major
