import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


def fingerprint(source: str, rule: str, file_path: str, line_number: int | None) -> str:
    """Stable identity for a finding across scans, independent of scan
    order or timestamp — this is what makes Security Regression Testing
    possible: the same underlying issue produces the same fingerprint run
    to run, so SecurityIntelligenceLayer can tell "still open" apart from
    "new" and "no longer detected" instead of treating every scan as a
    fresh, unrelated list.
    """
    raw = f"{source}:{rule}:{file_path}:{line_number if line_number is not None else ''}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


class SecurityFinding(Base):
    """One finding from one NSIL scanner. Rows are never deleted on a
    re-scan — a finding that disappears gets `status` flipped to
    "resolved" (see security/nsil.py), so history of what was found and
    fixed survives, same append-only-with-status-transitions pattern as
    EvolutionRoadmapItem.
    """

    __tablename__ = "security_findings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)

    # "sast" | "secret" | "config" | "dependency"
    source: Mapped[str] = mapped_column(String(20), index=True)
    rule: Mapped[str] = mapped_column(String(200))
    severity: Mapped[str] = mapped_column(String(20))
    file_path: Mapped[str] = mapped_column(String(1000))
    line_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str] = mapped_column(Text)

    # sha256(source:rule:file_path:line_number)[:32] — see fingerprint()
    # above. Unique per repository, not globally, since the same rule at
    # the same relative path in two different repos is coincidence, not
    # the same finding.
    fingerprint: Mapped[str] = mapped_column(String(32), index=True)

    # "open" | "resolved"
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
