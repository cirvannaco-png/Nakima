import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base


class SandboxRun(Base):
    __tablename__ = "sandbox_runs"
    __table_args__ = (
        CheckConstraint(
            "trigger IN ('ci_failure', 'cve_scan', 'synthetic_injection', 'manual')",
            name="ck_sandbox_runs_trigger",
        ),
        CheckConstraint(
            "status IN ('queued', 'provisioning', 'running', 'awaiting_review', "
            "'approved', 'rejected', 'expired', 'failed')",
            name="ck_sandbox_runs_status",
        ),
        CheckConstraint(
            "outcome IS NULL OR outcome IN ('fix_correct', 'fix_incorrect', 'no_fix_found', 'user_rejected')",
            name="ck_sandbox_runs_outcome",
        ),
        CheckConstraint(
            "synthetic_injection_used = false OR trigger = 'synthetic_injection'",
            name="ck_sandbox_runs_synthetic_trigger",
        ),
        Index("ix_sandbox_runs_repository_created", "repository_id", "created_at"),
        Index("ix_sandbox_runs_provider_installation_created", "provider_installation_id", "created_at"),
        Index("ix_sandbox_runs_status_expires", "status", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id", ondelete="RESTRICT"), nullable=False)
    # Snapshot the owning installation at run creation. This remains stable
    # if the provider later removes, suspends, or reassigns the repository.
    provider_installation_id: Mapped[int] = mapped_column(
        ForeignKey("provider_installations.id", ondelete="RESTRICT"), nullable=False
    )
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", server_default="queued")
    source_commit_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    container_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    container_image: Mapped[str | None] = mapped_column(String(255), nullable=True)
    network_isolated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    synthetic_injection_used: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    result_schema_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    diagnosis: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    proposed_fix_diff: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_models_consulted: Mapped[list | None] = mapped_column(JSON, nullable=True)
    full_test_suite_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC) + timedelta(hours=2),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    repository = relationship("Repository", foreign_keys=[repository_id])
    reviews = relationship("RunReview", back_populates="sandbox_run", cascade="all, delete-orphan")
    candidates = relationship("ModelCandidateFix", back_populates="sandbox_run", cascade="all, delete-orphan")
    provider_installation = relationship("ProviderInstallation")


class RunReview(Base):
    __tablename__ = "run_reviews"
    __table_args__ = (
        CheckConstraint("decision IN ('approved', 'rejected')", name="ck_run_reviews_decision"),
        Index("ix_run_reviews_run_reviewed", "sandbox_run_id", "reviewed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    sandbox_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sandbox_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    reviewed_by: Mapped[str] = mapped_column(String(255), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    sandbox_run = relationship("SandboxRun", back_populates="reviews")


class ModelCandidateFix(Base):
    __tablename__ = "model_candidate_fixes"
    __table_args__ = (
        Index("ix_model_candidate_fixes_run", "sandbox_run_id"),
        Index(
            "uq_model_candidate_fixes_one_selected_per_run",
            "sandbox_run_id",
            unique=True,
            postgresql_where=text("candidate_status = 'selected'"),
            sqlite_where=text("candidate_status = 'selected'"),
        ),
        CheckConstraint(
            "candidate_status IN ('proposed', 'applied', 'tested', 'rejected', 'selected')",
            name="ck_model_candidate_fixes_status",
        ),
        CheckConstraint(
            "candidate_status NOT IN ('tested', 'selected') OR "
            "(test_suite_passed IS NOT NULL AND tested_at IS NOT NULL "
            "AND applied_commit_sha IS NOT NULL AND test_results IS NOT NULL)",
            name="ck_model_candidate_fixes_tested_has_result",
        ),
        CheckConstraint(
            "candidate_status != 'selected' OR test_suite_passed IS TRUE",
            name="ck_model_candidate_fixes_selected_passed",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    sandbox_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sandbox_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    candidate_diff: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="proposed", server_default="proposed"
    )
    test_suite_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    applied_commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    test_results: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    judge_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    retained_for_training: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    sandbox_run = relationship("SandboxRun", back_populates="candidates")
