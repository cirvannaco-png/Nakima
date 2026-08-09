from fastapi import APIRouter

from api.v1.endpoints import documents, health, intelligence, market_research, neis, repositories, security, tasks

router = APIRouter()
router.include_router(health.router, prefix="/health", tags=["health"])
router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
router.include_router(repositories.router, prefix="/repositories", tags=["repositories"])
router.include_router(neis.router, prefix="/neis", tags=["neis"])
router.include_router(intelligence.router, prefix="/intelligence", tags=["intelligence"])
router.include_router(security.router, prefix="/security", tags=["security"])
router.include_router(documents.router, prefix="/documents", tags=["documents"])
router.include_router(market_research.router, prefix="/market-research", tags=["market-research"])
