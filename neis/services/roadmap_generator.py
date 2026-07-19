import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.neis.evolution_roadmap import EvolutionRoadmap, EvolutionRoadmapItem, RoadmapStatus


class RoadmapGenerator:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def build(
        self, repository_id: int, reality_id: uuid.UUID | None, recommendations: list[dict], summary: str
    ) -> EvolutionRoadmap:
        await self._supersede_active(repository_id)

        roadmap = EvolutionRoadmap(
            repository_id=repository_id,
            based_on_reality_id=reality_id,
            status=RoadmapStatus.ACTIVE,
            summary=summary,
        )
        self.session.add(roadmap)
        await self.session.flush()

        for rec in sorted(recommendations, key=lambda r: r["priority_score"], reverse=True):
            self.session.add(
                EvolutionRoadmapItem(
                    roadmap_id=roadmap.id,
                    category=rec["category"],
                    title=rec["title"],
                    rationale=rec["rationale"],
                    priority_score=rec["priority_score"],
                    effort_estimate=rec["effort_estimate"],
                )
            )

        await self.session.commit()
        await self.session.refresh(roadmap, attribute_names=["items"])
        return roadmap

    async def _supersede_active(self, repository_id: int):
        stmt = select(EvolutionRoadmap).where(
            EvolutionRoadmap.repository_id == repository_id, EvolutionRoadmap.status == RoadmapStatus.ACTIVE
        )
        active_roadmaps = (await self.session.execute(stmt)).scalars().all()
        for r in active_roadmaps:
            r.status = RoadmapStatus.SUPERSEDED
