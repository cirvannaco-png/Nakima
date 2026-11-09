from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base


class ProviderInstallation(Base):
    """A provider installation/account that defines a repository tenant boundary.

    External IDs are strings because providers use different identifier
    formats. The internal integer key is the only FK target inside Nakima.
    """

    __tablename__ = "provider_installations"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "external_installation_id",
            name="uq_provider_installations_provider_external_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    external_installation_id: Mapped[str] = mapped_column(String(255), nullable=False)
    account_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    account_login: Mapped[str | None] = mapped_column(String(255), nullable=True)
    account_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        onupdate=lambda: datetime.now(UTC).replace(tzinfo=None),
    )

    repositories = relationship("Repository", back_populates="provider_installation")
