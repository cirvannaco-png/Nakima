"""Research Agent. Mirrors neis/analyzers/tech_scout.py's shape deliberately:
one outbound network call per unit of work, individually try/excepted, so
one failing query degrades that query's signal count to zero instead of
failing the whole scan. Produces raw ExternalSignal rows only — it does not
decide what's credible (that's judge.py) or what to do about it (that's
opportunity_engine.py). Keeping "go find things" and "decide if they're
worth trusting" as separate classes is the whole point of the Judge Agent:
a single research+filter step can't be independently tested or audited.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from market_research.search import SearchClient, get_default_search_client
from models.neis.external_opportunity import ExternalSignal, SignalSource

logger = logging.getLogger(__name__)


class ResearchScout:
    def __init__(self, session: AsyncSession, search_client: SearchClient | None = None):
        self.session = session
        self.search_client = search_client or get_default_search_client()

    async def scan(self, repository_id: int, queries: list[str]) -> list[ExternalSignal]:
        """`queries` are caller-supplied research topics — e.g.
        ["shopify abandoned cart recovery competitors", "ecommerce checkout
        UX trends 2026"]. Deliberately not inferred from the repo here:
        letting the Opportunity Engine's own output loop back into what
        gets searched for next is a separate, higher-risk feature (it can
        drift the research topic away from what the human actually wants
        investigated) and isn't part of this change.
        """
        signals: list[ExternalSignal] = []
        for query in queries:
            signals.extend(await self._scan_one(repository_id, query))
        return signals

    async def _scan_one(self, repository_id: int, query: str) -> list[ExternalSignal]:
        try:
            results = await self.search_client.search(query, settings.MARKET_RESEARCH_MAX_RESULTS_PER_QUERY)
        except Exception as e:
            logger.warning(f"market_research.research_scout: query '{query}' failed — {e}")
            return []

        signals = []
        for result in results:
            signal = ExternalSignal(
                repository_id=repository_id,
                source=SignalSource.WEB_SEARCH,
                query=query,
                title=result.title,
                url=result.url,
                snippet=result.snippet,
            )
            self.session.add(signal)
            signals.append(signal)

        await self.session.flush()
        return signals
