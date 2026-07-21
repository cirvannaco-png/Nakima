from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas import HealthScoreResponse, RepositoryIndexRequest, RepositoryIndexResponse
from core.limiter import limiter
from database.session import get_db
from models.repository import Repository
from repository.engine import RepositoryEngine
from repository.graph_builder import GraphBuilder
from repository.health import HealthScorer

router = APIRouter()


@router.get("/", response_model=list[dict])
async def list_repositories(
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    """List all indexed repositories."""
    result = await db.execute(select(Repository).order_by(Repository.created_at.desc()))
    repos = result.scalars().all()
    return [
        {
            "id": r.id,
            "full_name": r.full_name,
            "github_repo_id": r.github_repo_id,
            # Health / quality fields are computed on-demand via /health —
            # listed here as None until a health check has been run.
            "health_score": None,
            "language": None,
            "stars": None,
            "complexity_score": None,
            "coverage_score": None,
            "dependency_score": None,
            "indexed_at": r.created_at.isoformat(),
        }
        for r in repos
    ]


@router.post("/index", response_model=RepositoryIndexResponse)
@limiter.limit("10/minute")
async def index_repository(
    request: Request,
    req: RepositoryIndexRequest,
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    result = await db.execute(select(Repository).where(Repository.full_name == req.repo_full_name))
    repo = result.scalar_one_or_none()
    if not repo:
        repo = Repository(full_name=req.repo_full_name)
        db.add(repo)
        await db.commit()
        await db.refresh(repo)

    engine = RepositoryEngine(f"https://github.com/{req.repo_full_name}.git", req.github_token)
    await engine.clone()

    builder = GraphBuilder(engine.working_dir, repo.id, db)
    graph = await builder.build_full_graph()

    return RepositoryIndexResponse(
        repository_id=repo.id, nodes_created=graph.number_of_nodes(), edges_created=graph.number_of_edges()
    )


@router.get("/{repo_full_name:path}/health", response_model=HealthScoreResponse)
async def get_repository_health(
    repo_full_name: str,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    github_token: str = Header(..., alias="X-GitHub-Token"),
):
    result = await db.execute(select(Repository).where(Repository.full_name == repo_full_name))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not indexed yet — POST /index first")

    engine = RepositoryEngine(f"https://github.com/{repo_full_name}.git", github_token)
    await engine.clone()
    scorer = HealthScorer(Path(engine.working_dir))
    result = await scorer.score()
    return HealthScoreResponse(**result)
