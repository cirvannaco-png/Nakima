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

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from github import Github
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas import (
    NEISAnalyzeRequest,
    NEISAnalyzeResponse,
    NEISIntentRequest,
    NEISIntentResponse,
    NEISRealityResponse,
    NEISRoadmapItemResponse,
    NEISRoadmapItemStatusRequest,
    NEISRoadmapItemStatusResponse,
    NEISRoadmapResponse,
)
from database.session import get_db
from models.neis.evolution_roadmap import ItemStatus
from models.neis.project_reality import ProjectRealityModel
from models.repository import Repository
from neis.services.evolution_service import EvolutionService
from repository.engine import RepositoryEngine

logger = logging.getLogger(__name__)

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


@router.patch("/{repo_full_name:path}/roadmap/items/{item_id}", response_model=NEISRoadmapItemStatusResponse)
async def update_roadmap_item_status(
    repo_full_name: str,
    item_id: uuid.UUID,
    req: NEISRoadmapItemStatusRequest,
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """The human review gate. EvolutionRoadmapItem.status has existed since
    0003_neis.py but had no write path — every recommendation from
    POST /analyze sat at PROPOSED forever. This lets a reviewer accept or
    dismiss one item at a time.

    Accepting with a github_token opens a GitHub issue for the item, which
    is what actually connects this to orchestrator/workflow.py: creating
    the issue triggers GitHub's "issues" webhook exactly like a
    human-authored issue would, and POST /github/webhook already routes
    that event into WorkflowOrchestrator.handle_webhook_event — nothing new
    needed on that side. Idempotent on item.issue_number: a second accept
    call (or a client retry) won't open a duplicate issue.

    Issue creation failing doesn't fail the status update — the review
    decision (accepted/dismissed) is the primary effect of this call and
    is worth keeping even if GitHub is unreachable; the item just stays
    ACCEPTED with issue_url=None until a retry succeeds.
    """
    repo = await _get_repository_or_404(db, repo_full_name)

    service = EvolutionService(db)
    item = await service.update_item_status(repo.id, item_id, ItemStatus(req.status))
    if not item:
        raise HTTPException(status_code=404, detail="Roadmap item not found for this repository")

    if item.status == ItemStatus.ACCEPTED and req.github_token and not item.issue_number:
        try:
            gh_issue = (
                Github(req.github_token)
                .get_repo(repo_full_name)
                .create_issue(
                    title=f"[NEIS] {item.title}",
                    body=(
                        f"{item.rationale}\n\n"
                        f"---\n"
                        f"Category: {item.category.value} · Effort: {item.effort_estimate.value} · "
                        f"Priority score: {item.priority_score:.2f}\n"
                        f"Opened from an accepted NEIS roadmap recommendation "
                        f"(item {item.id})."
                    ),
                )
            )
            item = await service.attach_issue(item, gh_issue.number, gh_issue.html_url)
        except Exception as e:
            # Same posture as githubapp/app.py's GitHubAppAuthError handling:
            # log with enough detail to debug, don't leak it as a raw 500.
            logger.warning(f"Failed to open GitHub issue for roadmap item {item.id}: {e}")

    return NEISRoadmapItemStatusResponse(id=str(item.id), status=item.status.value, issue_url=item.issue_url)
