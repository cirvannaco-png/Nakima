"""Models for market_research/ — the Research -> Judge -> Innovation pipeline
that runs *alongside* neis/analyzers/innovation_engine.py, never through it.

Deliberately separate tables from evolution_roadmap.py. EvolutionRoadmapItem
rows are, by construction, traceable to a measured fact about the repository
(see innovation_engine.py's module docstring on why that guarantee exists).
Nothing in this file can honestly make that same guarantee — a competitor's
feature list or a framework announcement is external, unverified-by-Nakima
information, and an LLM is involved in turning it into a proposal. Keeping
these in their own tables, with their own status machine, means a caller can
never accidentally treat an ExternalOpportunity as if it had the roadmap's
evidentiary standard. The only bridge between the two is explicit: promoting
an ACCEPTED opportunity copies it into a real EvolutionRoadmapItem (see
market_research/promotion.py), at which point it's subject to the same
human-acceptance gate as every other roadmap item before it can reach the
Coding Agent.
"""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base


class SignalSource(enum.StrEnum):
    WEB_SEARCH = "web_search"


class JudgeVerdict(enum.StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class OpportunityStatus(enum.StrEnum):
    # Mirrors ItemStatus in evolution_roadmap.py (PROPOSED/ACCEPTED/DISMISSED)
    # but kept as a distinct enum rather than reused, so a future change to
    # one status machine can't silently affect the other.
    PROPOSED = "proposed"
    PROMOTED = "promoted"  # copied into an EvolutionRoadmapItem — see promotion.py
    DISMISSED = "dismissed"


class ExternalSignal(Base):
    """One raw research finding — e.g. one search result — before judging.
    Persisted even when rejected: a full record of what the Research Agent
    found and why the Judge Agent did or didn't trust it is more useful for
    debugging and for tuning the judge prompt than only keeping the winners.
    """

    __tablename__ = "external_signals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)

    source: Mapped[SignalSource] = mapped_column(Enum(SignalSource))
    # The research topic this signal was gathered for, e.g. "abandoned cart
    # recovery ecommerce" — set by whoever triggers a scan, not inferred.
    query: Mapped[str] = mapped_column(String(500))

    title: Mapped[str] = mapped_column(String(500))
    url: Mapped[str] = mapped_column(String(2000))
    snippet: Mapped[str] = mapped_column(Text)

    judge_verdict: Mapped[JudgeVerdict] = mapped_column(Enum(JudgeVerdict), default=JudgeVerdict.PENDING)
    # Required whenever judge_verdict != PENDING — see judge.py. Not
    # enforced at the DB layer (SQLite test DB + Postgres both allow
    # nullable Text here) but every write path that sets a verdict also
    # sets this in the same call.
    judge_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    collected_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))
    judged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ExternalOpportunity(Base):
    """An Opportunity Engine proposal synthesized from one or more ACCEPTED
    ExternalSignal rows. Explicitly labeled speculative in every field name
    and in how it's surfaced (see api/v1/endpoints/market_research.py) —
    there is no code path where this reaches ImplementationAgent without a
    human promoting it first.
    """

    __tablename__ = "external_opportunities"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)

    title: Mapped[str] = mapped_column(String(500))
    # What the opportunity is and why the Opportunity Engine proposed it —
    # written by the provider, always attributed as such to the reader.
    description: Mapped[str] = mapped_column(Text)
    # 0-10, provider's own stated confidence — a self-report, not a
    # verified score. Surfaced as-is; never used to auto-promote anything.
    confidence: Mapped[float] = mapped_column(Float)

    status: Mapped[OpportunityStatus] = mapped_column(Enum(OpportunityStatus), default=OpportunityStatus.PROPOSED)
    # Set by promotion.py when status -> PROMOTED. Nullable because most
    # opportunities never leave PROPOSED/DISMISSED — same pattern as
    # EvolutionRoadmapItem.issue_number.
    promoted_roadmap_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("evolution_roadmap_items.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))

    source_signals: Mapped[list["ExternalOpportunitySignal"]] = relationship(back_populates="opportunity")


class ExternalOpportunitySignal(Base):
    """Join table: which ExternalSignal rows an ExternalOpportunity was
    synthesized from. Kept explicit (rather than a JSON array of IDs on
    ExternalOpportunity) so provenance survives a signal being queried
    independently and so this join can be indexed both directions.
    """

    __tablename__ = "external_opportunity_signals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("external_opportunities.id"), index=True)
    signal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("external_signals.id"), index=True)

    opportunity: Mapped[ExternalOpportunity] = relationship(back_populates="source_signals")
