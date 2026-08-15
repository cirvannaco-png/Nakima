"""
api/diff_review_routes.py

FastAPI router for:
  1. Diff review: list pending hunks, accept/edit/reject, swap the model
     for a single hunk (re-invokes only that hunk's Implementer step,
     not a full re-plan).
  2. Narrative agent: on-demand PDF export of contribution data.

Wire into your main app with:
    app.include_router(diff_review_router, prefix="/api")

Assumes:
  - `get_db` dependency yielding a SQLAlchemy session (matches your
    existing api/ routes pattern)
  - `providers.registry.get_provider(model_id)` returns a provider with
    a `.generate_patch(file_path, instruction, context)` method — adjust
    to whatever your actual providers/ interface looks like
  - orchestrator's Implementer step is reachable as
    `orchestrator.implementer.regenerate_hunk(...)` — adjust import path
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.provenance_model import ProvenanceRecordORM
from database.session import get_db  # adjust to your actual session dependency
from core.provenance import hunk_hash
from reports.contribution_report import generate_contribution_report

# adjust these two imports to your actual module paths
from providers.registry import get_provider
from orchestrator.implementer import regenerate_hunk

diff_review_router = APIRouter(tags=["diff-review"])


# ---------- Schemas ----------

class HunkActionRequest(BaseModel):
    action: str  # "accepted" | "edited" | "rejected"
    human_actor: str
    final_diff_text: Optional[str] = None  # required if action == "edited"


class ModelSwapRequest(BaseModel):
    model_id: str
    human_actor: str


# ---------- Diff review endpoints ----------

@diff_review_router.get("/repos/{owner}/{repo}/prs/{pr_number}/hunks")
def list_hunks(owner: str, repo: str, pr_number: int, db: Session = Depends(get_db)):
    full_repo = f"{owner}/{repo}"
    records = (
        db.query(ProvenanceRecordORM)
        .filter(ProvenanceRecordORM.repo == full_repo, ProvenanceRecordORM.pr_number == pr_number)
        .order_by(ProvenanceRecordORM.created_at)
        .all()
    )
    return {"pr_number": pr_number, "hunks": [r.to_dict() for r in records]}


@diff_review_router.post("/hunks/{record_id}/action")
def act_on_hunk(record_id: str, body: HunkActionRequest, db: Session = Depends(get_db)):
    record = db.query(ProvenanceRecordORM).filter_by(record_id=record_id).first()
    if not record:
        raise HTTPException(404, "Hunk not found")

    if body.action not in ("accepted", "edited", "rejected"):
        raise HTTPException(400, "action must be accepted, edited, or rejected")

    if body.action == "edited" and not body.final_diff_text:
        raise HTTPException(400, "final_diff_text required when action=edited")

    record.human_actor = body.human_actor
    record.accepted_verbatim = body.action == "accepted"

    if body.action == "edited":
        record.contributor_type = "human_edited_ai"
        record.hunk_hash = hunk_hash(body.final_diff_text)
    elif body.action == "rejected":
        # rejection doesn't delete history — it stays in the log as a
        # rejected AI attempt, which is itself provenance-relevant.
        record.contributor_type = "ai_agent"
        record.accepted_verbatim = False

    db.commit()
    return record.to_dict()


@diff_review_router.post("/hunks/{record_id}/model")
def swap_model(record_id: str, body: ModelSwapRequest, db: Session = Depends(get_db)):
    """Re-generates this single hunk with a different model. Does not
    touch any other hunk and does not re-run the Planner step."""
    record = db.query(ProvenanceRecordORM).filter_by(record_id=record_id).first()
    if not record:
        raise HTTPException(404, "Hunk not found")

    provider = get_provider(body.model_id)
    if provider is None:
        raise HTTPException(400, f"Unknown model: {body.model_id}")

    new_diff = regenerate_hunk(
        repo=record.repo,
        file_path=record.file_path,
        issue_ref=record.issue_ref,
        prompt_ref=record.prompt_ref,
        provider=provider,
    )

    record.model_id = body.model_id
    record.contributor_type = "ai_agent"
    record.human_actor = body.human_actor
    record.accepted_verbatim = None  # unknown again until re-reviewed
    record.hunk_hash = hunk_hash(new_diff)
    record.created_at = datetime.now(timezone.utc)

    db.commit()
    return {"record": record.to_dict(), "new_diff": new_diff}


# ---------- Narrative agent: contribution report ----------

@diff_review_router.get("/repos/{owner}/{repo}/contribution-report.pdf")
def contribution_report(owner: str, repo: str, db: Session = Depends(get_db)):
    full_repo = f"{owner}/{repo}"
    records = db.query(ProvenanceRecordORM).filter(ProvenanceRecordORM.repo == full_repo).all()

    if not records:
        raise HTTPException(404, f"No provenance data for {full_repo}")

    by_type: dict = {}
    by_agent: dict = {}
    by_human: dict = {}
    total_added = 0
    total_removed = 0

    for r in records:
        total_added += r.lines_added or 0
        total_removed += r.lines_removed or 0

        by_type.setdefault(r.contributor_type, {"count": 0, "lines_added": 0, "lines_removed": 0})
        by_type[r.contributor_type]["count"] += 1
        by_type[r.contributor_type]["lines_added"] += r.lines_added or 0
        by_type[r.contributor_type]["lines_removed"] += r.lines_removed or 0

        if r.agent_name:
            by_agent[r.agent_name] = by_agent.get(r.agent_name, 0) + 1
        if r.human_actor:
            by_human[r.human_actor] = by_human.get(r.human_actor, 0) + 1

    summary = {
        "repo": full_repo,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_records": len(records),
        "total_lines_added": total_added,
        "total_lines_removed": total_removed,
        "by_contributor_type": by_type,
        "by_agent": by_agent,
        "by_human": by_human,
        "records": [r.to_dict() for r in records],
    }

    tmp = NamedTemporaryFile(delete=False, suffix=".pdf")
    generate_contribution_report(summary, tmp.name)

    return FileResponse(
        tmp.name,
        media_type="application/pdf",
        filename=f"{repo}-contribution-report.pdf",
    )
