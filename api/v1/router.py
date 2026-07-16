from fastapi import APIRouter

from api.v1.endpoints import health, tasks

router = APIRouter()
router.include_router(health.router, prefix="/health", tags=["health"])
router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
