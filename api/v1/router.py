from fastapi import APIRouter

from api.v1.endpoints import attachments, cicd, documents, health, intelligence, market_research, monitoring, neis, repositories, security, tasks

router = APIRouter()
router.include_router(health.router, prefix="/health", tags=["health"])
router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
router.include_router(attachments.router, prefix="/attachments", tags=["attachments"])
router.include_router(cicd.router, prefix="/cicd/repositories", tags=["cicd"])
router.include_router(monitoring.router, prefix="/monitoring", tags=["monitoring"])
router.include_router(repositories.router, prefix="/repositories", tags=["repositories"])
router.include_router(neis.router, prefix="/neis", tags=["neis"])
router.include_router(intelligence.router, prefix="/intelligence", tags=["intelligence"])
router.include_router(security.router, prefix="/security", tags=["security"])
router.include_router(documents.router, prefix="/documents", tags=["documents"])
router.include_router(market_research.router, prefix="/market-research", tags=["market-research"])
