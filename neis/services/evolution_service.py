"""Orchestrates one NEIS analysis run: model the repo's current reality,
scout upstream dependency versions, extract structural patterns, generate
recommendations against stated user intent, and persist a roadmap.

Unlike validation/pipeline.py's ValidationPipeline — which stops at the
first failing stage because a broken build makes every later stage
meaningless — this orchestrator degrades per-stage instead of stopping,
because the stages here are independent signals, not a dependency chain:
a PyPI outage that breaks TechScout shouldn't discard the structural
patterns ProjectModeler and PatternExtractor already found. ProjectModeler
itself is the one stage that can't degrade — every later stage reads its
output — so its failure does abort the run.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.neis.evolution_roadmap import EvolutionRoadmap, RoadmapStatus
from models.neis.user_intent import UserIntent
from neis.analyzers.innovation_engine import InnovationReasoningEngine
from neis.analyzers.pattern_extractor import PatternExtractor
from neis.analyzers.project_modeler import ProjectModeler
from neis.analyzers.tech_scout import TechScout
from neis.services.roadmap_generator import RoadmapGenerator
from providers.manager import provider_manager

logger = logging.getLogger(__name__)


class EvolutionService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def run_analysis(self, repo_dir, repository_id: int) -> dict:
        stages_completed: list[str] = []
        stages_failed: dict[str, str] = {}

        reality = await ProjectModeler(self.session).build_snapshot(repo_dir, repository_id)
        stages_completed.append("project_modeler")

        tech_intel = []
        try:
            tech_intel = await TechScout(self.session).scan(repository_id, reality.dependencies)
            stages_completed.append("tech_scout")
        except Exception as e:
            logger.warning(f"NEIS tech_scout stage failed for repository {repository_id}: {e}")
            stages_failed["tech_scout"] = str(e)

        patterns = []
        try:
            patterns = await PatternExtractor(self.session).extract(repository_id)
            stages_completed.append("pattern_extractor")
        except Exception as e:
            logger.warning(f"NEIS pattern_extractor stage failed for repository {repository_id}: {e}")
            stages_failed["pattern_extractor"] = str(e)

        intent = await self._get_active_intent(repository_id)

        engine = InnovationReasoningEngine()
        recommendations = engine.generate_recommendations(reality, tech_intel, patterns, intent)

        provider = None
        try:
            provider = provider_manager.get_provider()
        except Exception:
            pass  # no provider configured — summarize() falls back to a deterministic summary
        summary = await engine.summarize(recommendations, provider)

        roadmap = await RoadmapGenerator(self.session).build(repository_id, reality.id, recommendations, summary)
        stages_completed.append("roadmap_generator")

        return {
            "roadmap_id": roadmap.id,
            "reality_id": reality.id,
            "recommendation_count": len(recommendations),
            "stages_completed": stages_completed,
            "stages_failed": stages_failed,
        }

    async def _get_active_intent(self, repository_id: int) -> UserIntent | None:
        stmt = select(UserIntent).where(UserIntent.repository_id == repository_id, UserIntent.is_active.is_(True))
        return (await self.session.execute(stmt)).scalars().first()

    async def set_intent(
        self, repository_id: int, goals: list[str], constraints: list[str], priority_weights: dict, notes: str | None
    ) -> UserIntent:
        previous = await self._get_active_intent(repository_id)
        if previous:
            previous.is_active = False

        intent = UserIntent(
            repository_id=repository_id,
            goals=goals,
            constraints=constraints,
            priority_weights=priority_weights,
            notes=notes,
            is_active=True,
        )
        self.session.add(intent)
        await self.session.commit()
        await self.session.refresh(intent)
        return intent

    async def get_latest_roadmap(self, repository_id: int) -> EvolutionRoadmap | None:
        # selectinload is required here, not optional: this object gets
        # returned to callers (the API layer, or tests) that access
        # `.items` after this method has already returned and the async
        # context that fetched it is gone. Without eager loading, that
        # access triggers an implicit lazy-load with no event loop
        # available to run it in (sqlalchemy.exc.MissingGreenlet) — this
        # was caught by tests/test_neis_evolution_service.py, not by any
        # of the per-module unit tests, because none of them read a
        # roadmap back through a second, independent query.
        stmt = (
            select(EvolutionRoadmap)
            .options(selectinload(EvolutionRoadmap.items))
            .where(EvolutionRoadmap.repository_id == repository_id, EvolutionRoadmap.status == RoadmapStatus.ACTIVE)
        )
        return (await self.session.execute(stmt)).scalars().first()
