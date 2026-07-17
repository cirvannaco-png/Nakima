from fastapi import APIRouter

from api.v1.endpoints import health, repositories, tasks

router = APIRouter()
router.include_router(health.router, prefix="/health", tags=["health"])
router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
router.include_router(repositories.router, prefix="/repositories", tags=["repositories"])
