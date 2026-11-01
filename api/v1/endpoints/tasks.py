import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db
from models.repository import Repository
from models.task import Task, TaskStatus

router = APIRouter()


# ── Request / response shapes ──────────────────────────────────────────────────


class TaskCreateRequest(BaseModel):
    repo_full_name: str
    issue_number: int
    github_token: str | None = None


class TaskResponse(BaseModel):
    id: str
    repo_full_name: str
    issue_number: int | None
    title: str
    status: str
    pipeline_stage: str
    pr_url: str | None
    error: str | None
    created_at: str
    updated_at: str | None
    output_branch: str | None = None


# ── Helpers ────────────────────────────────────────────────────────────────────

_STAGE_MAP = {
    TaskStatus.PENDING: "pending",
    TaskStatus.IN_PROGRESS: "implement",
    TaskStatus.SUCCESS: "pr",
    TaskStatus.FAILED: "failed",
}


def _task_to_response(task: Task, repo_full_name: str) -> dict:
    payload = task.event_payload or {}
    return {
        "id": str(task.id),
        "repo_full_name": repo_full_name,
        "issue_number": payload.get("issue_number") or (payload.get("issue") or {}).get("number"),
        "title": task.title,
        "status": task.status.value,
        "pipeline_stage": _STAGE_MAP.get(task.status, "pending"),
        "pr_url": task.pr_url,
        "error": task.error,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "output_branch": payload.get("output_branch"),
    }


async def _get_or_create_repo(db: AsyncSession, repo_full_name: str) -> Repository:
    result = await db.execute(select(Repository).where(Repository.full_name == repo_full_name))
    repo = result.scalar_one_or_none()
    if not repo:
        repo = Repository(full_name=repo_full_name)
        db.add(repo)
        await db.commit()
        await db.refresh(repo)
    return repo


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.post("/", response_model=TaskResponse)
async def create_task(
    req: TaskCreateRequest,
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """Manually trigger Nakima to process an issue into a PR."""
    repo = await _get_or_create_repo(db, req.repo_full_name)

    task = Task(
        repository_id=repo.id,
        title=f"Issue #{req.issue_number} — {req.repo_full_name}",
        description=f"Manually triggered task for issue #{req.issue_number}",
        status=TaskStatus.PENDING,
        event_payload={
            "issue_number": req.issue_number,
            "repo_full_name": req.repo_full_name,
            "github_token": bool(req.github_token),  # store presence only — never store tokens
            "triggered_at": datetime.now(UTC).replace(tzinfo=None).isoformat(),
            "source": "dashboard",
        },
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    # Hand off to the orchestrator workflow asynchronously.
    # Import here to avoid circular import at module level.
    try:
        import asyncio

        from orchestrator.workflow import run_task

        asyncio.create_task(
            run_task(
                task_id=task.id,
                repo_full_name=req.repo_full_name,
                issue_number=req.issue_number,
                github_token=req.github_token,
            )
        )
    except Exception:
        # If the orchestrator isn't available the task is still created and
        # visible in the dashboard — it just stays in PENDING state.
        pass

    return _task_to_response(task, req.repo_full_name)


class NaturalLanguageTaskRequest(BaseModel):
    repo_full_name: str = Field(min_length=3, max_length=200)
    title: str = Field(min_length=4, max_length=200)
    description: str = Field(min_length=10, max_length=12000)
    publish_pr: bool = True

class RunNaturalLanguageTaskRequest(BaseModel):
    github_token: SecretStr

@router.post("/requests", response_model=TaskResponse, status_code=201)
async def create_natural_language_request(req: NaturalLanguageTaskRequest, db: AsyncSession = Depends(get_db)):
    """Create a natural-language change proposal; evidence can be uploaded before execution."""
    if req.repo_full_name.count("/") != 1 or any(not part for part in req.repo_full_name.split("/")):
        raise HTTPException(status_code=422, detail="repo_full_name must use owner/repository format")
    repo = await _get_or_create_repo(db, req.repo_full_name)
    payload = {
        "issue": {"number": None, "title": req.title, "body": req.description},
        "nakima": {"source": "natural_language", "publish_pr": req.publish_pr, "created_at": datetime.now(UTC).isoformat()},
    }
    task = Task(repository_id=repo.id, title=req.title, description=req.description, status=TaskStatus.PENDING, event_payload=payload)
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return _task_to_response(task, repo.full_name)

@router.post("/{task_id}/run", response_model=TaskResponse)
async def run_natural_language_request(task_id: uuid.UUID, req: RunNaturalLanguageTaskRequest, db: AsyncSession = Depends(get_db)):
    """Start a pending natural-language proposal without persisting the GitHub token."""
    result = await db.execute(select(Task, Repository.full_name).join(Repository, Task.repository_id == Repository.id).where(Task.id == task_id))
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")
    task, repo_full_name = row
    payload = task.event_payload or {}
    if (payload.get("nakima") or {}).get("source") != "natural_language":
        raise HTTPException(status_code=400, detail="Only natural-language requests can be started here")
    if task.status != TaskStatus.PENDING:
        raise HTTPException(status_code=409, detail="The request is no longer pending")
    token = req.github_token.get_secret_value().strip()
    if not token:
        raise HTTPException(status_code=422, detail="A GitHub token with repository write access is required")
    import asyncio
    from orchestrator.workflow import WorkflowOrchestrator
    asyncio.create_task(WorkflowOrchestrator().process_task(str(task.id), repo_full_name, payload, token))
    return _task_to_response(task, repo_full_name)


@router.get("/", response_model=list[TaskResponse])
async def list_tasks(
    limit: int = 50,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """List recent tasks, newest first. Optionally filter by status."""
    stmt = (
        select(Task, Repository.full_name)
        .join(Repository, Task.repository_id == Repository.id)
        .order_by(Task.created_at.desc())
        .limit(limit)
    )
    if status:
        try:
            stmt = stmt.where(Task.status == TaskStatus(status))
        except ValueError as err:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status '{status}'. Valid values: {[s.value for s in TaskStatus]}",
            ) from err
    rows = (await db.execute(stmt)).all()
    return [_task_to_response(task, full_name) for task, full_name in rows]


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    result = await db.execute(
        select(Task, Repository.full_name)
        .join(Repository, Task.repository_id == Repository.id)
        .where(Task.id == task_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    task, full_name = row
    return _task_to_response(task, full_name)
