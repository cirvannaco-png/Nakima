"""Orchestrates one market-research run: scout external signals for the
given queries, judge them, and (only for ACCEPTED ones) generate
opportunities. Same per-stage degradation posture as
neis/services/evolution_service.py's EvolutionService and for the same
reason: a judge-provider outage shouldn't discard signals the scout already
found (they stay PENDING for a later judge_pending call), and a search
outage shouldn't prevent judging whatever's already sitting PENDING from an
earlier run.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from market_research.judge import JudgeAgent
from market_research.opportunity_engine import OpportunityEngine
from market_research.research_scout import ResearchScout
from models.neis.external_opportunity import ExternalOpportunity, ExternalSignal, JudgeVerdict
from providers.manager import provider_manager

logger = logging.getLogger(__name__)


class MarketResearchService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def run(self, repository_id: int, queries: list[str], repo_context: str) -> dict:
        stages_completed: list[str] = []
        stages_failed: dict[str, str] = {}

        signals: list[ExternalSignal] = []
        try:
            signals = await ResearchScout(self.session).scan(repository_id, queries)
            stages_completed.append("research_scout")
        except Exception as e:
            logger.warning(f"market_research: research_scout stage failed for repository {repository_id}: {e}")
            stages_failed["research_scout"] = str(e)

        provider = self._get_provider()

        judged: list[ExternalSignal] = []
        try:
            judged = await JudgeAgent(self.session, provider).judge_pending(repository_id, repo_context)
            stages_completed.append("judge")
        except Exception as e:
            logger.warning(f"market_research: judge stage failed for repository {repository_id}: {e}")
            stages_failed["judge"] = str(e)

        opportunities: list[ExternalOpportunity] = []
        try:
            opportunities = await OpportunityEngine(self.session, provider).generate(
                repository_id, repo_context, judged
            )
            stages_completed.append("opportunity_engine")
        except Exception as e:
            logger.warning(f"market_research: opportunity_engine stage failed for repository {repository_id}: {e}")
            stages_failed["opportunity_engine"] = str(e)

        await self.session.commit()

        accepted_count = sum(1 for s in judged if s.judge_verdict == JudgeVerdict.ACCEPTED)
        return {
            "signals_collected": len(signals),
            "signals_judged": len(judged),
            "signals_accepted": accepted_count,
            "opportunities_generated": len(opportunities),
            "stages_completed": stages_completed,
            "stages_failed": stages_failed,
        }

    def _get_provider(self):
        try:
            return provider_manager.get_provider()
        except Exception:
            return None  # judge/opportunity stages degrade explicitly — see their own fail-closed handling
