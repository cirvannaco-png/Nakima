import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class EngineeringReport(Base):
    """Metadata for one generated Engineering Intelligence Report PDF.
    Append-only and versioned per repository — a new report is never a
    replacement for an old one, same append-only philosophy as
    ProjectRealityModel and EngineeringDecision. The PDF bytes themselves
    live on disk at `file_path` (see core.config.Settings.REPORTS_DIR),
    not in this table.
    """

    __tablename__ = "engineering_reports"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)

    version: Mapped[int] = mapped_column(Integer)
    file_path: Mapped[str] = mapped_column(String(1000))
    executive_summary: Mapped[str] = mapped_column(Text)
    # Which of the spec's sections actually had data to render, e.g.
    # ["project_dna", "engineering_decisions", "recommendations"] — a
    # section with nothing to say is omitted from the PDF rather than
    # rendered as an empty header, and this column records which ones
    # that happened for so a caller doesn't have to re-open the PDF to
    # find out.
    sections_included: Mapped[list] = mapped_column(JSON, default=list)

    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
