"""Engineering Decision Registry + Event Log endpoints. Same auth posture
as api/v1/endpoints/neis.py and api/v1/endpoints/repositories.py — no
per-caller authorization beyond the repository already being indexed.
All writes here are to Nakima's own database, never to the analyzed
repository, same blast-radius argument as NEIS.
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas import DecisionCreateRequest, DecisionResponse, EventResponse, ReportResponse
from database.session import get_db
from intelligence.decision_registry import DecisionRegistry
from intelligence.event_log import EventLog
from models.report import EngineeringReport
from models.repository import Repository
from reports.pdf_generator import ReportGenerator

router = APIRouter()


async def _get_repository_or_404(db: AsyncSession, repo_full_name: str) -> Repository:
    result = await db.execute(select(Repository).where(Repository.full_name == repo_full_name))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not indexed yet — POST /repositories/index first")
    return repo


def _decision_to_response(row) -> DecisionResponse:
    return DecisionResponse(
        id=str(row.id),
        repository_id=row.repository_id,
        context=row.context,
        problem=row.problem,
        decision=row.decision,
        justification=row.justification,
        alternatives=row.alternatives,
        consequences=row.consequences,
        related_files=row.related_files,
        related_issues=row.related_issues,
        author=row.author,
        created_at=row.created_at.isoformat(),
    )


def _event_to_response(row) -> EventResponse:
    return EventResponse(
        id=str(row.id),
        repository_id=row.repository_id,
        task_id=str(row.task_id) if row.task_id else None,
        decision_id=str(row.decision_id) if row.decision_id else None,
        timestamp=row.timestamp.isoformat(),
        author=row.author,
        task_description=row.task_description,
        files_modified=row.files_modified,
        reason=row.reason,
        chosen_solution=row.chosen_solution,
        risk_level=row.risk_level,
        verification_status=row.verification_status,
        tests_executed=row.tests_executed,
    )


@router.post("/{repo_full_name:path}/decisions", response_model=DecisionResponse)
async def create_decision(
    repo_full_name: str,
    req: DecisionCreateRequest,
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    repo = await _get_repository_or_404(db, repo_full_name)
    row = await DecisionRegistry(db, repo.id).record(**req.model_dump())
    return _decision_to_response(row)


@router.get("/{repo_full_name:path}/decisions", response_model=list[DecisionResponse])
async def list_decisions(
    repo_full_name: str,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    repo = await _get_repository_or_404(db, repo_full_name)
    rows = await DecisionRegistry(db, repo.id).list_for_repository(limit=limit)
    return [_decision_to_response(r) for r in rows]


@router.get("/{repo_full_name:path}/events", response_model=list[EventResponse])
async def list_events(
    repo_full_name: str,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    repo = await _get_repository_or_404(db, repo_full_name)
    rows = await EventLog(db, repo.id).list_for_repository(limit=limit)
    return [_event_to_response(r) for r in rows]


def _report_to_response(row: EngineeringReport) -> ReportResponse:
    return ReportResponse(
        id=str(row.id),
        repository_id=row.repository_id,
        version=row.version,
        executive_summary=row.executive_summary,
        sections_included=row.sections_included,
        generated_at=row.generated_at.isoformat(),
    )


@router.post("/{repo_full_name:path}/reports/generate", response_model=ReportResponse)
async def generate_report(
    repo_full_name: str,
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    repo = await _get_repository_or_404(db, repo_full_name)
    row = await ReportGenerator(db, repo.id).generate()
    return _report_to_response(row)


@router.get("/{repo_full_name:path}/reports", response_model=list[ReportResponse])
async def list_reports(
    repo_full_name: str,
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    repo = await _get_repository_or_404(db, repo_full_name)
    stmt = (
        select(EngineeringReport)
        .where(EngineeringReport.repository_id == repo.id)
        .order_by(EngineeringReport.version.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [_report_to_response(r) for r in rows]


@router.get("/{repo_full_name:path}/reports/{report_id}/download")
async def download_report(
    repo_full_name: str,
    report_id: str,
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    repo = await _get_repository_or_404(db, repo_full_name)
    report = await db.get(EngineeringReport, report_id)
    if not report or report.repository_id != repo.id:
        raise HTTPException(status_code=404, detail="Report not found for this repository")
    return FileResponse(
        report.file_path,
        media_type="application/pdf",
        filename=f"{repo.full_name.replace('/', '_')}_v{report.version}.pdf",
    )
