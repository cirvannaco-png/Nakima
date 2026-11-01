"""Token-protected read-only logs, metrics and incident investigation."""
import hmac
from fastapi import APIRouter,Header,HTTPException
from pydantic import BaseModel,Field
from prometheus_client import CONTENT_TYPE_LATEST,generate_latest
from starlette.responses import Response
from core.config import settings
from monitoring import REGISTRY,recent_logs
from providers.manager import provider_manager
router=APIRouter()
class Investigation(BaseModel):
    question:str=Field(min_length=8,max_length=1000)
    log_limit:int=Field(default=100,ge=1,le=200)
def authorize(token):
    expected=settings.PRODUCTION_MONITORING_TOKEN
    if settings.ENVIRONMENT=="production" and not expected:raise HTTPException(503,"Set PRODUCTION_MONITORING_TOKEN to enable monitoring")
    if expected and (not token or not hmac.compare_digest(token,expected)):raise HTTPException(401,"Invalid monitoring token")
@router.get("/metrics")
async def metrics(x_nakima_monitoring_token:str|None=Header(default=None)):
    authorize(x_nakima_monitoring_token);return Response(generate_latest(REGISTRY),media_type=CONTENT_TYPE_LATEST)
@router.get("/logs")
async def logs(limit:int=100,x_nakima_monitoring_token:str|None=Header(default=None)):
    authorize(x_nakima_monitoring_token);return {"scope":"current_process_recent_logs","capacity":500,"logs":recent_logs(limit),"note":"Use an external log exporter for durable multi-instance history."}
@router.post("/investigations")
async def investigate(req:Investigation,x_nakima_monitoring_token:str|None=Header(default=None)):
    authorize(x_nakima_monitoring_token)
    context={"task":"Read-only incident investigation. Separate facts from hypotheses, cite timestamps and metric names, recommend safe reproduction and fixes. Do not modify code or run commands.","logs":recent_logs(req.log_limit),"metrics":generate_latest(REGISTRY).decode("utf-8",errors="replace")[:12000]}
    try:result=await provider_manager.get_provider().debug(req.question,context)
    except Exception as exc:raise HTTPException(503,f"Investigation unavailable: {type(exc).__name__}") from exc
    return {"provider":result.model,"investigation":result.content,"changes_applied":False}
