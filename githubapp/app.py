import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from core.limiter import limiter
from githubapp.auth import GitHubAppAuthError, github_auth
from githubapp.webhooks import verify_webhook
from orchestrator.workflow import WorkflowOrchestrator

logger = logging.getLogger(__name__)
router = APIRouter()

EVENTS_OF_INTEREST = {"issues", "pull_request", "push"}

# The normal issue-to-PR workflow needs write access, but only to the
# repository that emitted the webhook. Sandbox runs must request a separate,
# contents:read-only token rather than reusing this workflow token.
WORKFLOW_REPOSITORY_PERMISSIONS = {
    "contents": "write",
    "issues": "read",
    "metadata": "read",
    "pull_requests": "write",
}


@router.post("/webhook")
@limiter.limit("60/minute")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    event = await verify_webhook(request)

    if event.event_type not in EVENTS_OF_INTEREST:
        logger.info(f"Ignoring webhook event: {event.event_type}")
        return {"status": "ignored", "event": event.event_type}

    if not event.repo_full_name:
        return {"status": "ignored", "reason": "no repository in payload"}
    if not event.repository_id or event.repository_id <= 0:
        raise HTTPException(status_code=400, detail="Webhook payload is missing a valid repository id")

    try:
        token = await github_auth.get_repository_installation_token(
            event.installation_id,
            event.repository_id,
            WORKFLOW_REPOSITORY_PERMISSIONS,
        )
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
