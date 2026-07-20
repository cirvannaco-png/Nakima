"""
Webhook signature verification + payload extraction.

The original scaffold had three different, mutually incompatible versions of
verify_webhook() across the three source files (one returned a bare dict, one
returned a 2-tuple, one returned a 3-tuple) — none of which agreed with how
github/app.py actually called it. This is the single reconciled version.
"""

import hashlib
import hmac
from dataclasses import dataclass

from fastapi import HTTPException, Request

from core.config import settings


@dataclass
class WebhookEvent:
    event_type: str
    payload: dict
    installation_id: int
    repo_full_name: str | None  # None for installation-level events (e.g. "installation")


async def verify_webhook(request: Request) -> WebhookEvent:
    """Verifies the HMAC signature and extracts the fields the orchestrator needs.

    Raises HTTPException(401) on a bad/missing signature and HTTPException(400)
    if the payload is missing fields we require (installation id).
    """
    signature = request.headers.get("X-Hub-Signature-256")
    if not signature:
        raise HTTPException(status_code=401, detail="Missing X-Hub-Signature-256 header")

    if not settings.GITHUB_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="GITHUB_WEBHOOK_SECRET is not configured")

    body = await request.body()
    expected = "sha256=" + hmac.new(settings.GITHUB_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload = await request.json()

    installation_id = payload.get("installation", {}).get("id")
    if not installation_id:
        raise HTTPException(status_code=400, detail="Payload missing installation id")

    event_type = request.headers.get("X-GitHub-Event", "unknown")
    repo_full_name = payload.get("repository", {}).get("full_name")

    return WebhookEvent(
        event_type=event_type,
        payload=payload,
        installation_id=int(installation_id),
        repo_full_name=repo_full_name,
    )
