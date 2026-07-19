"""NSIL endpoints. Same clone-then-analyze shape and auth posture as
api/v1/endpoints/neis.py — scanning needs the repo checked out on disk,
so this clones the same way NEIS's /analyze does. All writes here are to
Nakima's own database (SecurityFinding rows), never to the analyzed
repository.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas import SecurityFindingResponse, SecurityScanRequest, SecurityScanResponse
from database.session import get_db
from models.repository import Repository
from models.security import SecurityFinding
from repository.engine import RepositoryEngine
from security.nsil import SecurityIntelligenceLayer

router = APIRouter()


async def _get_repository_or_404(db: AsyncSession, repo_full_name: str) -> Repository:
    result = await db.execute(select(Repository).where(Repository.full_name == repo_full_name))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not indexed yet — POST /repositories/index first")
    return repo


@router.post("/{repo_full_name:path}/scan", response_model=SecurityScanResponse)
async def run_security_scan(
    repo_full_name: str,
    req: SecurityScanRequest,
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    repo = await _get_repository_or_404(db, repo_full_name)

    engine = RepositoryEngine(f"https://github.com/{repo_full_name}.git", req.github_token)
    await engine.clone()

    result = await SecurityIntelligenceLayer(db, repo.id).scan(engine.working_dir)
    return SecurityScanResponse(
        score=result.score,
        counts_by_severity=result.counts_by_severity,
        total_open=result.total_open,
        new_finding_count=result.new_finding_count,
        resolved_finding_count=result.resolved_finding_count,
        scanners_run=result.scanners_run,
        scanners_skipped=result.scanners_skipped,
    )


@router.get("/{repo_full_name:path}/findings", response_model=list[SecurityFindingResponse])
async def list_findings(
    repo_full_name: str,
    status: str = "open",
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    repo = await _get_repository_or_404(db, repo_full_name)
    stmt = select(SecurityFinding).where(SecurityFinding.repository_id == repo.id)
    if status != "all":
        stmt = stmt.where(SecurityFinding.status == status)
    stmt = stmt.order_by(SecurityFinding.severity, SecurityFinding.last_seen_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return [
        SecurityFindingResponse(
            id=str(r.id),
            source=r.source,
            rule=r.rule,
            severity=r.severity,
            file_path=r.file_path,
            line_number=r.line_number,
            detail=r.detail,
            status=r.status,
            first_seen_at=r.first_seen_at.isoformat(),
            last_seen_at=r.last_seen_at.isoformat(),
        )
        for r in rows
    ]
