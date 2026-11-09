from datetime import UTC, datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base


class ProviderInstallationMembership(Base):
    """Explicit grant binding an OIDC principal to one provider installation."""

    __tablename__ = "provider_installation_memberships"
    __table_args__ = (
        Index(
            "uq_installation_membership_active_principal",
            "provider_installation_id",
            "principal_issuer",
            "principal_subject",
            unique=True,
            postgresql_where=text("is_active = true"),
            sqlite_where=text("is_active = 1"),
        ),
        CheckConstraint(
            "role IN ('owner', 'admin', 'maintainer', 'reviewer', 'viewer')",
            name="ck_installation_membership_role",
        ),
        CheckConstraint(
            "length(principal_issuer) > 0 AND length(principal_subject) > 0",
            name="ck_installation_membership_principal",
        ),
        CheckConstraint(
            "is_active = true OR (revoked_at IS NOT NULL AND "
            "revoked_by_issuer IS NOT NULL AND revoked_by_subject IS NOT NULL "
            "AND revocation_reason IS NOT NULL)",
            name="ck_installation_membership_revocation_audit",
        ),
        Index(
            "ix_installation_membership_active_role",
            "provider_installation_id",
            "is_active",
            "role",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    provider_installation_id: Mapped[int] = mapped_column(
        ForeignKey("provider_installations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    principal_issuer: Mapped[str] = mapped_column(String(512), nullable=False)
    principal_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    granted_by_issuer: Mapped[str] = mapped_column(String(512), nullable=False)
    granted_by_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    revoked_by_issuer: Mapped[str | None] = mapped_column(String(512), nullable=True)
    revoked_by_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    provider_installation = relationship("ProviderInstallation")
