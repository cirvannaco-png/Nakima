from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.v1.router import router as v1_router
from core.config import settings
from core.limiter import limiter
from core.logging import setup_logging
from githubapp.app import router as github_router


OPENAPI_DESCRIPTION = """
**Nakima** is a multi-agent orchestration platform that plans, executes, and
verifies code changes across GitHub repositories.

* `/api/v1/tasks` — submit and inspect orchestration tasks
* `/api/v1/repositories` — register repos and query analysis / health
* `/api/v1/memory` — knowledge-graph queries and learning feedback
* `/api/v1/agents` — enumerate agents and capabilities
* `/github/webhook` — GitHub App webhook receiver (HMAC-verified)
"""

OPENAPI_TAGS = [
    {"name": "tasks", "description": "Task orchestration lifecycle."},
    {"name": "repositories", "description": "Repository analysis & health."},
    {"name": "memory", "description": "Knowledge graph & learning."},
    {"name": "agents", "description": "Agent registry."},
    {"name": "health", "description": "Liveness & readiness probes."},
    {"name": "github", "description": "GitHub App webhook."},
]


def create_app() -> FastAPI:
    setup_logging()
    app = FastAPI(
        title="Nakima",
        version=settings.VERSION,
        description=OPENAPI_DESCRIPTION,
        openapi_tags=OPENAPI_TAGS,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        contact={"name": "Nakima", "url": "https://github.com/cirvannaco-png/Nakima"},
        license_info={"name": "CC0-1.0"},
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.include_router(v1_router, prefix="/api/v1")
    # GitHub App webhook receiver — HMAC verified inside the handler.
    app.include_router(github_router, prefix="/github", tags=["github"])

    @app.get("/", tags=["health"], summary="Service banner")
    def root() -> dict:
        return {"service": settings.APP_NAME, "version": settings.VERSION, "docs": "/docs"}

    @app.get("/health", tags=["health"], summary="Liveness probe")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/ready", tags=["health"], summary="Readiness probe")
    def ready() -> dict:
        return {"status": "ready"}

    return app


app = create_app()
