"""Opportunity Engine — the Innovation Agent for external signals. Only ever
called with ExternalSignal rows the Judge Agent has already ACCEPTED. This
ordering is enforced by the caller (service.py), not by this class, but the
type of `signals` accepted here is still restricted to already-judged rows
so a caller can't accidentally hand it PENDING or REJECTED ones — see
generate().

Unlike neis/analyzers/innovation_engine.py, this class is unapologetically
LLM-driven: there is no deterministic way to turn "competitor X does Y" into
a product opportunity. That's exactly why every ExternalOpportunity it
produces stays quarantined in its own table with its own PROPOSED/PROMOTED/
DISMISSED status (see models/neis/external_opportunity.py) instead of
landing directly in EvolutionRoadmapItem.
"""

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from models.neis.external_opportunity import (
    ExternalOpportunity,
    ExternalOpportunitySignal,
    ExternalSignal,
    JudgeVerdict,
)
from providers.base import AIProvider

logger = logging.getLogger(__name__)

OPPORTUNITY_PROMPT_TEMPLATE = """You are proposing product opportunities for a software \
repository based on external research findings that have already been screened for relevance \
and credibility. Do not propose anything the findings below don't support.

Repository context: {repo_context}

Findings:
{findings}

Propose at most {max_opportunities} opportunities. Respond as a JSON array, nothing else. Each \
element: {{"title": str, "description": str (2-4 sentences, explain what and why, referencing \
which finding(s) support it), "confidence": number 0-10 (your own confidence, be conservative), \
"signal_indices": [int, ...] (1-based indices into the findings list above that support this \
opportunity)}}. Return [] if the findings don't support any credible opportunity."""


class OpportunityEngine:
    def __init__(self, session: AsyncSession, provider: AIProvider | None):
        self.session = session
        self.provider = provider

    async def generate(
        self, repository_id: int, repo_context: str, signals: list[ExternalSignal]
    ) -> list[ExternalOpportunity]:
        accepted = [s for s in signals if s.judge_verdict == JudgeVerdict.ACCEPTED]
        if not accepted:
            return []
        if not self.provider:
            logger.info("market_research.opportunity_engine: no provider configured — skipping, 0 opportunities")
            return []

        findings_text = "\n".join(f"{i + 1}. {s.title} — {s.snippet} ({s.url})" for i, s in enumerate(accepted))
        prompt = OPPORTUNITY_PROMPT_TEMPLATE.format(
            repo_context=repo_context,
            findings=findings_text,
            max_opportunities=settings.MARKET_RESEARCH_MAX_OPPORTUNITIES_PER_RUN,
        )

        try:
            response = await self.provider.plan(prompt, {"task": "external_opportunity_generation"})
            proposals = self._parse(response.content)
        except Exception as e:
            logger.warning(f"market_research.opportunity_engine: generation failed — {e}")
            return []

        opportunities = []
        for proposal in proposals[: settings.MARKET_RESEARCH_MAX_OPPORTUNITIES_PER_RUN]:
            opp = self._build_opportunity(repository_id, proposal, accepted)
            if opp:
                opportunities.append(opp)

        await self.session.flush()
        return opportunities

    def _build_opportunity(
        self, repository_id: int, proposal: dict, accepted: list[ExternalSignal]
    ) -> ExternalOpportunity | None:
        title = str(proposal.get("title", "")).strip()
        description = str(proposal.get("description", "")).strip()
        if not title or not description:
            return None  # malformed element — skip it, don't fail the whole batch

        try:
            confidence = max(0.0, min(10.0, float(proposal.get("confidence", 0))))
        except (TypeError, ValueError):
            confidence = 0.0

        opportunity = ExternalOpportunity(
            repository_id=repository_id, title=title, description=description, confidence=confidence
        )
        self.session.add(opportunity)

        for idx in proposal.get("signal_indices", []) or []:
            # 1-based indices as given to the prompt; silently skip
            # out-of-range ones rather than raising over a provider's
            # off-by-one — provenance is best-effort here, not load-bearing.
            i = idx - 1
            if isinstance(idx, int) and 0 <= i < len(accepted):
                self.session.add(ExternalOpportunitySignal(opportunity=opportunity, signal_id=accepted[i].id))

        return opportunity

    def _parse(self, content: str) -> list[dict]:
        content = content.strip()
        # Providers sometimes wrap JSON in a ```json fence despite the
        # prompt saying not to — strip it defensively rather than fail.
        if content.startswith("```"):
            content = content.strip("`")
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning(f"market_research.opportunity_engine: response was not valid JSON — {e}")
            return []

        if not isinstance(parsed, list):
            return []
        return [p for p in parsed if isinstance(p, dict)]
