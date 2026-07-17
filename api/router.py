from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.v1.router import router as v1_router
from core.limiter import limiter
from core.logging import setup_logging
from githubapp.app import router as github_router


def create_app() -> FastAPI:
    setup_logging()
    app = FastAPI(title="Nakima", version="1.0.0")

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.include_router(v1_router, prefix="/api/v1")
    # GitHub sends webhooks to /github/webhook — this was defined in
    # github/app.py in the original scaffold but never actually mounted
    # anywhere, so it would 404 on every real webhook delivery.
    app.include_router(github_router, prefix="/github", tags=["github"])
    return app


app = create_app()
