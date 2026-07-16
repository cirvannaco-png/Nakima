from fastapi import APIRouter

from core.config import settings

router = APIRouter()


@router.get("/")
async def health_check():
    return {"status": "ok", "version": settings.VERSION}
