import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class Ecosystem(str, enum.Enum):
    PYPI = "pypi"
    NPM = "npm"


class TechnologyIntel(Base):
    """What's actually current upstream for one dependency, as of the last
    scout run. Upserted per (repository_id, package_name, ecosystem) — this
    table tracks "latest known state per package", not history; pair it
    with the ProjectRealityModel snapshot that was current when it last ran
    if you need a point-in-time view.
    """

    __tablename__ = "technology_intel"
    __table_args__ = (UniqueConstraint("repository_id", "package_name", "ecosystem", name="uq_tech_intel_pkg"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)

    package_name: Mapped[str] = mapped_column(String(200), index=True)
    ecosystem: Mapped[Ecosystem] = mapped_column(Enum(Ecosystem))

    current_version: Mapped[str] = mapped_column(String(100))
    # Null means the scout couldn't resolve a latest version (package not
    # found upstream, or the registry call failed) — distinct from "we
    # checked and it's already current", which is is_outdated=False with a
    # real latest_version populated.
    latest_version: Mapped[str | None] = mapped_column(String(100), nullable=True)

    is_outdated: Mapped[bool] = mapped_column(Boolean, default=False)
    major_versions_behind: Mapped[int | None] = mapped_column(Integer, nullable=True)

    scanned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
