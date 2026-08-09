"""The explicit promotion gate. This is the only place in the codebase that
writes an ExternalOpportunity into EvolutionRoadmapItem — and therefore the
only path by which anything the Research/Judge/Opportunity pipeline found
can ever reach ImplementationAgent. There is no automatic or scheduled call
into this module anywhere; it only runs from a direct API call a human made
(see api/v1/endpoints/market_research.py), the same posture as
EvolutionService.update_item_status for ordinary roadmap items.

Once promoted, the resulting EvolutionRoadmapItem is indistinguishable in
shape from any other roadmap item and goes through the exact same
ACCEPTED -> GitHub issue -> orchestrator flow every other item does — this
module's job ends the moment the row is written.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.neis.evolution_roadmap import (
    EffortEstimate,
    EvolutionRoadmap,
    EvolutionRoadmapItem,
    ItemStatus,
    RecommendationCategory,
    RoadmapStatus,
)
from models.neis.external_opportunity import ExternalOpportunity, OpportunityStatus


class OpportunityPromoter:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def promote(self, repository_id: int, opportunity_id: uuid.UUID) -> EvolutionRoadmapItem:
        """Raises ValueError (caller maps to 4xx) for every precondition
        failure — no opportunity, wrong status, or no active roadmap to
        attach to — rather than silently no-op'ing, since a caller acting
        on a promotion request needs to know unambiguously whether it
        happened.
        """
        opportunity = await self._get_opportunity_or_raise(repository_id, opportunity_id)
        if opportunity.status != OpportunityStatus.PROPOSED:
            raise ValueError(f"Opportunity {opportunity_id} is {opportunity.status.value}, not proposed")

        roadmap = await self._get_active_roadmap_or_raise(repository_id)

        item = EvolutionRoadmapItem(
            roadmap_id=roadmap.id,
            category=RecommendationCategory.MARKET_OPPORTUNITY,
            title=opportunity.title,
            rationale=(
                f"{opportunity.description}\n\n"
                f"Promoted from external market research (opportunity {opportunity.id}, "
                f"confidence {opportunity.confidence:.1f}/10 as self-reported by the provider "
                f"that proposed it — not independently verified)."
            ),
            # Every promoted opportunity starts at the same priority
            # regardless of its self-reported confidence — confidence is
            # informational, not a scoring input, for the same reason
            # it isn't used to auto-promote: it's a self-report from the
            # provider that generated it, not a measured signal.
            priority_score=5.0,
            effort_estimate=EffortEstimate.MEDIUM,
            status=ItemStatus.PROPOSED,
        )
        self.session.add(item)
        await self.session.flush()

        opportunity.status = OpportunityStatus.PROMOTED
        opportunity.promoted_roadmap_item_id = item.id

        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def dismiss(self, repository_id: int, opportunity_id: uuid.UUID) -> ExternalOpportunity:
        opportunity = await self._get_opportunity_or_raise(repository_id, opportunity_id)
        opportunity.status = OpportunityStatus.DISMISSED
        await self.session.commit()
        await self.session.refresh(opportunity)
        return opportunity

    async def _get_opportunity_or_raise(self, repository_id: int, opportunity_id: uuid.UUID) -> ExternalOpportunity:
        stmt = select(ExternalOpportunity).where(
            ExternalOpportunity.id == opportunity_id, ExternalOpportunity.repository_id == repository_id
        )
        opportunity = (await self.session.execute(stmt)).scalars().first()
        if not opportunity:
            raise ValueError(f"No opportunity {opportunity_id} for repository {repository_id}")
        return opportunity

    async def _get_active_roadmap_or_raise(self, repository_id: int) -> EvolutionRoadmap:
        stmt = select(EvolutionRoadmap).where(
            EvolutionRoadmap.repository_id == repository_id, EvolutionRoadmap.status == RoadmapStatus.ACTIVE
        )
        roadmap = (await self.session.execute(stmt)).scalars().first()
        if not roadmap:
            raise ValueError(
                f"No active roadmap for repository {repository_id} — run POST /neis/{{repo}}/analyze first"
            )
        return roadmap
