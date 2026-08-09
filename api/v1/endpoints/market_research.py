"""Market research endpoints. Same auth posture and blast-radius reasoning
as api/v1/endpoints/neis.py — every write here lands in Nakima's own
database (external_signals, external_opportunities), never in the analyzed
repository itself. The one exception is POST /promote, which writes an
EvolutionRoadmapItem — still Nakima's own database, and still requires the
same human accept/github_token step as any other roadmap item before it can
open a GitHub issue or reach the orchestrator.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas import (
    ExternalOpportunityResponse,
    ExternalSignalResponse,
    MarketResearchScanRequest,
    MarketResearchScanResponse,
    OpportunityPromoteResponse,
)
from database.session import get_db
from market_research.promotion import OpportunityPromoter
from market_research.service import MarketResearchService
from models.neis.external_opportunity import ExternalOpportunity, ExternalSignal
from models.repository import Repository

logger = logging.getLogger(__name__)

router = APIRouter()


async def _get_repository_or_404(db: AsyncSession, repo_full_name: str) -> Repository:
    result = await db.execute(select(Repository).where(Repository.full_name == repo_full_name))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not indexed yet — POST /repositories/index first")
    return repo


@router.post("/{repo_full_name:path}/scan", response_model=MarketResearchScanResponse)
async def run_scan(
    repo_full_name: str,
    req: MarketResearchScanRequest,
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    repo = await _get_repository_or_404(db, repo_full_name)
    result = await MarketResearchService(db).run(repo.id, req.queries, req.repo_context)
    return MarketResearchScanResponse(**result)


@router.get("/{repo_full_name:path}/signals", response_model=list[ExternalSignalResponse])
async def list_signals(repo_full_name: str, db: AsyncSession = Depends(get_db)):  # noqa: B008
    repo = await _get_repository_or_404(db, repo_full_name)
    stmt = (
        select(ExternalSignal)
        .where(ExternalSignal.repository_id == repo.id)
        .order_by(ExternalSignal.collected_at.desc())
    )
    signals = (await db.execute(stmt)).scalars().all()
    return [
        ExternalSignalResponse(
            id=str(s.id),
            query=s.query,
            title=s.title,
            url=s.url,
            snippet=s.snippet,
            judge_verdict=s.judge_verdict.value,
            judge_rationale=s.judge_rationale,
        )
        for s in signals
    ]


@router.get("/{repo_full_name:path}/opportunities", response_model=list[ExternalOpportunityResponse])
async def list_opportunities(repo_full_name: str, db: AsyncSession = Depends(get_db)):  # noqa: B008
    from sqlalchemy.orm import selectinload  # noqa: PLC0415  (local import mirrors evolution_service.py's pattern)

    repo = await _get_repository_or_404(db, repo_full_name)
    stmt = (
        select(ExternalOpportunity)
        .options(selectinload(ExternalOpportunity.source_signals))
        .where(ExternalOpportunity.repository_id == repo.id)
        .order_by(ExternalOpportunity.created_at.desc())
    )
    opportunities = (await db.execute(stmt)).scalars().all()
    return [
        ExternalOpportunityResponse(
            id=str(o.id),
            title=o.title,
            description=o.description,
            confidence=o.confidence,
            status=o.status.value,
            source_signal_ids=[str(s.signal_id) for s in o.source_signals],
            created_at=o.created_at.isoformat(),
        )
        for o in opportunities
    ]


@router.post("/{repo_full_name:path}/opportunities/{opportunity_id}/promote", response_model=OpportunityPromoteResponse)
async def promote_opportunity(
    repo_full_name: str,
    opportunity_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """The explicit human gate — see market_research/promotion.py's module
    docstring. This is the only endpoint that moves anything from the
    market-research pipeline into the trusted roadmap.
    """
    repo = await _get_repository_or_404(db, repo_full_name)
    try:
        item = await OpportunityPromoter(db).promote(repo.id, opportunity_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return OpportunityPromoteResponse(
        opportunity_id=str(opportunity_id), roadmap_item_id=str(item.id), roadmap_item_status=item.status.value
    )


@router.post(
    "/{repo_full_name:path}/opportunities/{opportunity_id}/dismiss", response_model=ExternalOpportunityResponse
)
async def dismiss_opportunity(
    repo_full_name: str,
    opportunity_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    repo = await _get_repository_or_404(db, repo_full_name)
    try:
        opportunity = await OpportunityPromoter(db).dismiss(repo.id, opportunity_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return ExternalOpportunityResponse(
        id=str(opportunity.id),
        title=opportunity.title,
        description=opportunity.description,
        confidence=opportunity.confidence,
        status=opportunity.status.value,
        source_signal_ids=[],
        created_at=opportunity.created_at.isoformat(),
    )
