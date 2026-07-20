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
from security.target_binding import RepoTargetBinding, TargetBindingError

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

    if req.run_pentest_simulator and not req.target_url:
        raise HTTPException(status_code=400, detail="run_pentest_simulator requires target_url to also be set.")

    if req.target_url:
        # DAST (and, when built, the Pentest Simulator) fires a real
        # outbound request at target_url — see security/target_binding.py
        # for why "the user typed a URL" isn't authorization on its own.
        # Requires the GitHub token so the binding check can look at what
        # this specific repo actually has on record, not what the caller
        # merely asserts.
        if not req.github_token:
            raise HTTPException(
                status_code=400, detail="github_token is required when target_url is supplied — see security/target_binding.py."
            )
        try:
            authorized = await RepoTargetBinding(repo_full_name, req.github_token).is_authorized(req.target_url)
        except TargetBindingError as e:
            raise HTTPException(status_code=502, detail=f"Couldn't verify target ownership: {e}") from None
        if not authorized:
            raise HTTPException(
                status_code=403,
                detail=f"{req.target_url} isn't associated with {repo_full_name} on GitHub (checked homepage, "
                "Pages, and deployment records) — refusing to scan a target this repository doesn't "
                "actually own.",
            )

    engine = RepositoryEngine(f"https://github.com/{repo_full_name}.git", req.github_token)
    await engine.clone()

    result = await SecurityIntelligenceLayer(db, repo.id).scan(
        engine.working_dir, target_url=req.target_url, run_pentest_simulator=req.run_pentest_simulator
    )
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
