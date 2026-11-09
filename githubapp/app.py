import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from core.limiter import limiter
from database.session import AsyncSessionLocal
from githubapp.auth import GitHubAppAuthError, github_auth
from githubapp.installation_sync import (
    require_active_github_repository_installation,
    sync_github_installation_event,
)
from githubapp.webhooks import verify_webhook
from orchestrator.workflow import WorkflowOrchestrator

logger = logging.getLogger(__name__)
router = APIRouter()

EVENTS_OF_INTEREST = {"issues", "pull_request", "push"}
INSTALLATION_EVENTS = {"installation", "installation_repositories"}


@router.post("/webhook")
@limiter.limit("60/minute")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    event = await verify_webhook(request)

    # Installation lifecycle webhooks define provider tenancy. They are
    # HMAC-verified and persisted locally; they do not need an automation
    # token and must never trigger the issue-to-PR workflow.
    if event.event_type in INSTALLATION_EVENTS:
        try:
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    sync_result = await sync_github_installation_event(
                        session,
                        event.event_type,
                        event.payload,
                    )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": sync_result["status"], "event": event.event_type, **sync_result}

    if event.event_type not in EVENTS_OF_INTEREST:
        logger.info(f"Ignoring webhook event: {event.event_type}")
        return {"status": "ignored", "event": event.event_type}

    if not event.repo_full_name:
        return {"status": "ignored", "reason": "no repository in payload"}

    # Do not let a normal issue/push/PR webhook create or transfer tenant
    # ownership. It must match a previously synchronized, active installation
    # and canonical GitHub repository ID before any workflow credential is
    # requested.
    try:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await require_active_github_repository_installation(
                    session,
                    event.payload.get("installation"),
                    event.payload.get("repository"),
                )
    except ValueError as exc:
        logger.warning("Rejected repository webhook because tenant ownership could not be verified: %s", exc)
        raise HTTPException(
            status_code=403,
            detail="Repository is not registered to an active GitHub App installation",
        ) from exc

    try:
        token = await github_auth.get_installation_token(event.installation_id)
    except GitHubAppAuthError as e:
        # Surfaces as a clean 502 instead of an unhandled 500 with a stack
        # trace leaking installation IDs / internal call paths — webhook
        # endpoints are public and shouldn't leak internals.
        logger.error(f"GitHub auth failed for installation {event.installation_id}: {e}")
        raise HTTPException(status_code=502, detail="Could not authenticate with GitHub") from e

    orchestrator = WorkflowOrchestrator()
    background_tasks.add_task(
        orchestrator.handle_webhook_event,
        event_type=event.event_type,
        payload=event.payload,
        repo_full_name=event.repo_full_name,
        github_token=token,
    )
    return {"status": "accepted"}
