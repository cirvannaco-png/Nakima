from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
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


@router.post("/index", response_model=RepositoryIndexResponse)
@limiter.limit("10/minute")
async def index_repository(request: Request, req: RepositoryIndexRequest, db: AsyncSession = Depends(get_db)):
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
async def get_repository_health(repo_full_name: str, github_token: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Repository).where(Repository.full_name == repo_full_name))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not indexed yet — POST /index first")

    engine = RepositoryEngine(f"https://github.com/{repo_full_name}.git", github_token)
    await engine.clone()
    scorer = HealthScorer(Path(engine.working_dir))
    result = await scorer.score()
    return HealthScoreResponse(**result)
