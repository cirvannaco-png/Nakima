import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class ProjectRealityModel(Base):
    """A single point-in-time snapshot of what a repository actually is —
    not what its README claims. Deliberately append-only (no update-in-place,
    no unique constraint on repository_id) so evolution over time can be
    tracked and compared snapshot-to-snapshot; "latest by created_at for
    this repository_id" is the current reality.
    """

    __tablename__ = "project_reality_models"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)

    # {"python": 42, "javascript": 3, ...} — file counts per detected language.
    languages: Mapped[dict] = mapped_column(JSON)
    # [{"name": "fastapi", "version": "0.115.0", "ecosystem": "pypi"}, ...]
    dependencies: Mapped[list] = mapped_column(JSON)
    # {"python": 3800, "javascript": 210, ...} — lines of code per language.
    loc_by_language: Mapped[dict] = mapped_column(JSON)

    file_count: Mapped[int] = mapped_column(Integer)
    test_file_count: Mapped[int] = mapped_column(Integer)

    # Mirrors repository.health.HealthScorer.score() — null if HealthScorer
    # itself returned null (e.g. no Python files in the repo at all).
    health_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    health_components: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), index=True)

    # Extension point for anything a specific analyzer run wants to attach
    # without a migration (e.g. framework detection heuristics). Not a
    # dumping ground for data that should be its own column — see the
    # models.knowledge module docstring for the same convention.
    extra_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
