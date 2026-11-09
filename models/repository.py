from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from models.provider_installation import ProviderInstallation  # noqa: F401


class Repository(Base):
    __tablename__ = "repositories"
    __table_args__ = (
        CheckConstraint(
            "sandbox_lab_opt_in = false OR "
            "(provider_installation_id IS NOT NULL "
            "AND sandbox_lab_consented_at IS NOT NULL "
            "AND sandbox_lab_consent_actor_id IS NOT NULL "
            "AND sandbox_lab_consent_version IS NOT NULL)",
            name="ck_repositories_lab_consent_complete",
        ),
        Index("ix_repositories_provider_installation_id", "provider_installation_id"),
        UniqueConstraint("id", "provider_installation_id", name="uq_repositories_id_installation"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    full_name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    github_repo_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Internal provider-installation row is the tenant boundary. The
    # external provider identifier is stored on that row, never used as a
    # cross-provider primary key. Legacy repositories remain unassigned.
    provider_installation_id: Mapped[int | None] = mapped_column(ForeignKey("provider_installations.id"), nullable=True)

    # Synthetic vulnerability injection and other Lab-only actions require
    # explicit, auditable repository consent. A missing/incomplete record
    # must fail closed; legacy repositories default to opted out.
    sandbox_lab_opt_in: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    sandbox_lab_consented_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sandbox_lab_consent_actor_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sandbox_lab_consent_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        onupdate=lambda: datetime.now(UTC).replace(tzinfo=None),
    )

    tasks = relationship("Task", back_populates="repository")
    provider_installation = relationship("ProviderInstallation", back_populates="repositories")
