import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class ProjectDocument(Base):
    """One uploaded document — the Project Upload Gateway's persistence
    layer. Stores the extracted text, not structured requirements/goals;
    turning extracted text into Project DNA fields (functional
    requirements, constraints, roadmap, etc. per the EIP spec) is a
    separate, not-yet-built step that would consume `extracted_text`,
    same division of labor as NSIL's scanners producing raw findings that
    reports/pdf_generator.py later renders — this model is the "gathers
    and structures information" layer, not the "reasons about it" layer.
    """

    __tablename__ = "project_documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)

    filename: Mapped[str] = mapped_column(String(500))
    file_type: Mapped[str] = mapped_column(String(20))  # "pdf" | "docx" | "markdown" | "text" | "json" | "yaml" | "sql"
    size_bytes: Mapped[int] = mapped_column(Integer)

    # sha256 of the raw uploaded bytes — duplicate detection key, scoped
    # per repository (the same file uploaded to two different repos isn't
    # a duplicate of anything).
    content_hash: Mapped[str] = mapped_column(String(64), index=True)

    # Append-only version counter per repository, same pattern as
    # EngineeringReport.version — re-uploading a file with the same name
    # doesn't overwrite anything.
    version: Mapped[int] = mapped_column(Integer)

    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # "clean" | "infected" | "unavailable" | "error" — see
    # security/virus_scanner.py. "unavailable" (no clamd configured) is
    # recorded explicitly rather than left null, so "never scanned" can
    # never be misread as "scanned and clean" by anyone querying this table.
    virus_scan_status: Mapped[str] = mapped_column(String(20), default="unavailable")

    # "processed" | "rejected" — a rejected upload (failed validation)
    # still gets a row, so "someone tried to upload X and it was
    # rejected because Y" is itself part of the audit trail.
    status: Mapped[str] = mapped_column(String(20), default="processed")
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), index=True)

    # Raw bytes are NOT populated by default (extracted_text is what
    # downstream consumers need); see documents/gateway.py's docstring
    # for why. Column kept nullable for a future opt-in "keep the
    # original file" mode rather than a schema change later.
    raw_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
