"""Authenticated read-only production log and metrics inspection."""
import hmac
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response
from core.config import settings
from monitoring import REGISTRY, recent_logs
from providers.manager import provider_manager

router = APIRouter()
class InvestigationRequest(BaseModel):
    question: str = Field(min_length=8, max_length=1000)
    log_limit: int = Field(default=100, ge=1, le=200)

def _authorize(token: str | None) -> None:
    expected = settings.PRODUCTION_MONITORING_TOKEN
    if settings.ENVIRONMENT == "production" and not expected:
        raise HTTPException(status_code=503, detail="Set PRODUCTION_MONITORING_TOKEN to enable production monitoring access")
    if expected and (token is None or not hmac.compare_digest(token, expected)):
        raise HTTPException(status_code=401, detail="Invalid monitoring access token")

@router.get("/metrics")
async def metrics(x_nakima_monitoring_token: str | None = Header(default=None)):
    _authorize(x_nakima_monitoring_token)
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)

@router.get("/logs")
async def logs(limit: int = 100, x_nakima_monitoring_token: str | None = Header(default=None)):
    _authorize(x_nakima_monitoring_token)
    return {"scope": "current_process_recent_logs", "capacity": 500, "logs": recent_logs(limit), "note": "Process-local only. Configure a log exporter/backend for durable multi-instance history."}

@router.post("/investigations")
async def investigate(req: InvestigationRequest, x_nakima_monitoring_token: str | None = Header(default=None)):
    _authorize(x_nakima_monitoring_token)
    context = {
        "task": "Read-only production incident investigation. Separate observed facts from hypotheses, cite timestamps and metric names, recommend safe reproduction and fixes, and do not edit code or run commands.",
        "recent_logs": recent_logs(req.log_limit),
        "metrics": generate_latest(REGISTRY).decode("utf-8", errors="replace")[:12000],
    }
    try:
        response = await provider_manager.get_provider().debug(req.question, context)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Monitoring investigation unavailable: {type(exc).__name__}") from exc
    return {"provider": response.model, "investigation": response.content, "changes_applied": False}
