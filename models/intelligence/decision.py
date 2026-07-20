import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class EngineeringDecision(Base):
    """One entry in the project's Engineering Decision Registry — the
    "institutional memory" concept from the EIP spec. Append-only: a
    decision that gets superseded later is recorded as a *new* row whose
    `context` references the old one, not an in-place edit, so the
    registry never loses a record of what was actually decided at the
    time.
    """

    __tablename__ = "engineering_decisions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)

    context: Mapped[str] = mapped_column(Text)
    problem: Mapped[str] = mapped_column(Text)
    # [{"option": "...", "rejected_because": "..."}, ...] — kept structured
    # rather than free text so a future PDF report or dashboard can render
    # a real alternatives table instead of parsing prose.
    alternatives: Mapped[list] = mapped_column(JSON, default=list)
    decision: Mapped[str] = mapped_column(Text)
    justification: Mapped[str] = mapped_column(Text)
    consequences: Mapped[str | None] = mapped_column(Text, nullable=True)

    related_files: Mapped[list] = mapped_column(JSON, default=list)
    related_issues: Mapped[list] = mapped_column(JSON, default=list)

    # Free-text author identifier — "nakima" for automated entries, or a
    # human handle for manually-logged architectural decisions. Not a FK
    # to a users table because Nakima doesn't have one yet (see
    # githubapp/auth.py — auth today is GitHub App installation tokens,
    # not per-human accounts).
    author: Mapped[str] = mapped_column(String(200), default="nakima")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    extra_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class EngineeringEvent(Base):
    """One structured record of an action Nakima (or a human) took —
    the "Engineering Intelligence Engine" event concept from the EIP spec.
    Written automatically by `orchestrator/workflow.py` at the end of a
    task (success or failure); can also be logged manually via the API
    for actions taken outside the automated pipeline.
    """

    __tablename__ = "engineering_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    decision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("engineering_decisions.id"), nullable=True, index=True
    )

    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    author: Mapped[str] = mapped_column(String(200), default="nakima")
    task_description: Mapped[str] = mapped_column(Text)

    files_modified: Mapped[list] = mapped_column(JSON, default=list)
    reason: Mapped[str] = mapped_column(Text)
    alternatives_considered: Mapped[list] = mapped_column(JSON, default=list)
    chosen_solution: Mapped[str] = mapped_column(Text)

    # {"metric": "estimate"} pairs, e.g. {"complexity": "low"} — deliberately
    # loose JSON rather than a fixed schema, since the EIP spec's Impact
    # Analysis Engine (performance/memory/maintainability/etc.) doesn't
    # exist yet; this is the landing spot for it once it does.
    expected_impact: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    measured_impact: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    risk_level: Mapped[str] = mapped_column(String(20), default="unknown")
    dependencies_affected: Mapped[list] = mapped_column(JSON, default=list)
    tests_executed: Mapped[list] = mapped_column(JSON, default=list)
    verification_status: Mapped[str] = mapped_column(String(30), default="unverified")

    extra_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
