"""Search backend for research_scout.py. Kept behind a Protocol, the same
shape as providers/base.py's AIProvider, so the Research Agent's tests never
need real network access and swapping search vendors never touches callers.

No backend is chosen by default yet — get_default_search_client() falls
back to NullSearchClient until MARKET_RESEARCH_SEARCH_API_KEY is set.
BraveSearchClient below is a reference implementation (cheap, keyed API,
simple REST shape), not a decision — swap it for whatever backend you
settle on; nothing else in market_research/ depends on it being Brave.
"""

import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

from core.config import settings

logger = logging.getLogger(__name__)

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


class SearchClient(Protocol):
    async def search(self, query: str, max_results: int) -> list[SearchResult]: ...


class BraveSearchClient:
    """Reference implementation, not the chosen backend — see module
    docstring. Requires MARKET_RESEARCH_SEARCH_API_KEY; see core/config.py
    for why an unset key degrades rather than errors.
    """

    def __init__(self, api_key: str, timeout: float | None = None):
        self.api_key = api_key
        self.timeout = timeout or settings.MARKET_RESEARCH_HTTP_TIMEOUT

    async def search(self, query: str, max_results: int) -> list[SearchResult]:
        headers = {"Accept": "application/json", "X-Subscription-Token": self.api_key}
        params = {"q": query, "count": max_results}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(BRAVE_SEARCH_URL, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in (data.get("web", {}) or {}).get("results", [])[:max_results]:
            results.append(
                SearchResult(
                    title=item.get("title", "") or "",
                    url=item.get("url", "") or "",
                    snippet=item.get("description", "") or "",
                )
            )
        return results


class NullSearchClient:
    """No API key configured. Returns no results rather than raising, so a
    scan with search disabled behaves like a scan that found nothing —
    the same degradation shape TechScout uses for an unreachable registry.
    """

    async def search(self, query: str, max_results: int) -> list[SearchResult]:
        logger.info("market_research.search: no MARKET_RESEARCH_SEARCH_API_KEY configured — returning no results")
        return []


def get_default_search_client() -> SearchClient:
    if settings.MARKET_RESEARCH_SEARCH_API_KEY:
        return BraveSearchClient(settings.MARKET_RESEARCH_SEARCH_API_KEY)
    return NullSearchClient()
