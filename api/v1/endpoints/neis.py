"""NEIS endpoints. Same auth posture as api/v1/endpoints/repositories.py —
a caller-supplied github_token, no per-caller authorization check beyond
that, no rate limit here — because that limitation already exists on
/repositories/index and hasn't been solved yet (see the audit discussion
in this repo's history). Not introducing new auth architecture here would
be pretending this endpoint is safer than the one it depends on; it isn't
any safer or less safe, since analyze() requires the repo to already be
indexed via that same endpoint first.

All writes here are to Nakima's own database (roadmaps, tech intel, user
intent) — never to the analyzed repository itself. That's a materially
smaller blast radius than the write-capable agents (refactoring, testing,
documentation), which is why this is wired up now while those wait on a
proper trigger + auth mechanism.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas import (
    NEISAnalyzeRequest,
    NEISAnalyzeResponse,
    NEISIntentRequest,
    NEISIntentResponse,
    NEISRealityResponse,
    NEISRoadmapItemResponse,
    NEISRoadmapResponse,
)
from database.session import get_db
from models.neis.project_reality import ProjectRealityModel
from models.repository import Repository
from neis.services.evolution_service import EvolutionService
from repository.engine import RepositoryEngine

router = APIRouter()


async def _get_repository_or_404(db: AsyncSession, repo_full_name: str) -> Repository:
    result = await db.execute(select(Repository).where(Repository.full_name == repo_full_name))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not indexed yet — POST /repositories/index first")
    return repo


@router.post("/{repo_full_name:path}/analyze", response_model=NEISAnalyzeResponse)
async def analyze_repository(
    repo_full_name: str,
    req: NEISAnalyzeRequest,
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    repo = await _get_repository_or_404(db, repo_full_name)

    engine = RepositoryEngine(f"https://github.com/{repo_full_name}.git", req.github_token)
    await engine.clone()

    result = await EvolutionService(db).run_analysis(engine.working_dir, repo.id)
    return NEISAnalyzeResponse(
        roadmap_id=str(result["roadmap_id"]),
        reality_id=str(result["reality_id"]),
        recommendation_count=result["recommendation_count"],
        stages_completed=result["stages_completed"],
        stages_failed=result["stages_failed"],
    )


@router.get("/{repo_full_name:path}/roadmap", response_model=NEISRoadmapResponse)
async def get_roadmap(repo_full_name: str, db: AsyncSession = Depends(get_db)):  # noqa: B008
    repo = await _get_repository_or_404(db, repo_full_name)

    roadmap = await EvolutionService(db).get_latest_roadmap(repo.id)
    if not roadmap:
        raise HTTPException(status_code=404, detail="No roadmap yet — POST /neis/{repo}/analyze first")

    return NEISRoadmapResponse(
        id=str(roadmap.id),
        status=roadmap.status.value,
        summary=roadmap.summary,
        generated_at=roadmap.generated_at.isoformat(),
        items=[
            NEISRoadmapItemResponse(
                id=str(item.id),
                category=item.category.value,
                title=item.title,
                rationale=item.rationale,
                priority_score=item.priority_score,
                effort_estimate=item.effort_estimate.value,
                status=item.status.value,
            )
            for item in sorted(roadmap.items, key=lambda i: i.priority_score, reverse=True)
        ],
    )


@router.get("/{repo_full_name:path}/reality", response_model=NEISRealityResponse)
async def get_latest_reality(repo_full_name: str, db: AsyncSession = Depends(get_db)):  # noqa: B008
    repo = await _get_repository_or_404(db, repo_full_name)

    stmt = (
        select(ProjectRealityModel)
        .where(ProjectRealityModel.repository_id == repo.id)
        .order_by(ProjectRealityModel.created_at.desc())
        .limit(1)
    )
    reality = (await db.execute(stmt)).scalars().first()
    if not reality:
        raise HTTPException(status_code=404, detail="No snapshot yet — POST /neis/{repo}/analyze first")

    return NEISRealityResponse(
        id=str(reality.id),
        languages=reality.languages,
        dependencies=reality.dependencies,
        loc_by_language=reality.loc_by_language,
        file_count=reality.file_count,
        test_file_count=reality.test_file_count,
        health_score=reality.health_score,
        created_at=reality.created_at.isoformat(),
    )


@router.post("/{repo_full_name:path}/intent", response_model=NEISIntentResponse)
async def set_intent(repo_full_name: str, req: NEISIntentRequest, db: AsyncSession = Depends(get_db)):  # noqa: B008
    repo = await _get_repository_or_404(db, repo_full_name)

    intent = await EvolutionService(db).set_intent(repo.id, req.goals, req.constraints, req.priority_weights, req.notes)
    return NEISIntentResponse(
        id=str(intent.id),
        goals=intent.goals,
        constraints=intent.constraints,
        priority_weights=intent.priority_weights,
        notes=intent.notes,
    )
