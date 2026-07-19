import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class UserIntent(Base):
    """What the maintainer actually wants for this repo, stated explicitly
    rather than inferred. Without this, InnovationReasoningEngine has no
    way to distinguish "outdated dependency, upgrade it" from "outdated
    dependency, deliberately pinned, don't suggest touching it" — every
    recommendation would be equally generic.

    Only one row should be treated as current per repository; the service
    layer (neis/services/evolution_service.py) enforces that by setting
    is_active=False on the previous row when a new one is created, rather
    than a DB-level constraint, since "replace the active intent" is a
    read-then-write operation anyway.
    """

    __tablename__ = "user_intents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)

    # Free-text goals, e.g. ["reduce startup latency", "prepare for a public API"].
    goals: Mapped[list] = mapped_column(JSON, default=list)
    # Free-text constraints, matched as case-insensitive substrings against a
    # recommendation's title+rationale to suppress it — a heuristic, not NLP.
    # e.g. ["no new dependencies", "keep Python 3.11 compatibility"].
    constraints: Mapped[list] = mapped_column(JSON, default=list)
    # {"dependency": 1.5, "security": 2.0, ...} — multiplies a recommendation
    # category's base priority_score. Missing categories default to 1.0.
    priority_weights: Mapped[dict] = mapped_column(JSON, default=dict)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
