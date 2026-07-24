import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base


class RoadmapStatus(str, enum.Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class RecommendationCategory(str, enum.Enum):
    DEPENDENCY = "dependency"
    ARCHITECTURE = "architecture"
    TESTING = "testing"
    SECURITY = "security"
    DOCUMENTATION = "documentation"


class EffortEstimate(str, enum.Enum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


class ItemStatus(str, enum.Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"
    COMPLETED = "completed"


class EvolutionRoadmap(Base):
    """One NEIS run's output. At most one ACTIVE roadmap per repository —
    generating a new one supersedes the previous ACTIVE row rather than
    deleting it, so roadmap history (what was recommended, what got
    accepted/dismissed) survives.
    """

    __tablename__ = "evolution_roadmaps"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    based_on_reality_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("project_reality_models.id"), nullable=True
    )

    status: Mapped[RoadmapStatus] = mapped_column(Enum(RoadmapStatus), default=RoadmapStatus.ACTIVE)
    # Deterministic template by default; may be an LLM-generated paragraph
    # if a provider call succeeded — see neis/analyzers/innovation_engine.py.
    # Either way this is a summary of the items below, never itself a
    # source of recommendations that skip the items table.
    summary: Mapped[str] = mapped_column(Text)

    generated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), index=True
    )

    items: Mapped[list["EvolutionRoadmapItem"]] = relationship(back_populates="roadmap")


class EvolutionRoadmapItem(Base):
    __tablename__ = "evolution_roadmap_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    roadmap_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evolution_roadmaps.id"), index=True)

    category: Mapped[RecommendationCategory] = mapped_column(Enum(RecommendationCategory))
    title: Mapped[str] = mapped_column(String(500))
    rationale: Mapped[str] = mapped_column(Text)
    # Higher = more important. Not normalized to a fixed range — see
    # innovation_engine.py's scoring docstring for how this is computed.
    priority_score: Mapped[float] = mapped_column(Float)
    effort_estimate: Mapped[EffortEstimate] = mapped_column(Enum(EffortEstimate))
    status: Mapped[ItemStatus] = mapped_column(Enum(ItemStatus), default=ItemStatus.PROPOSED)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))

    roadmap: Mapped[EvolutionRoadmap] = relationship(back_populates="items")
