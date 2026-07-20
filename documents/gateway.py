"""The Project Upload Gateway orchestrator: validate -> extract text ->
duplicate check -> version -> persist.

Two things explicitly out of scope, on purpose rather than by oversight:

1. Virus/malware scanning. The EIP spec lists it as a Gateway
   responsibility, and it's a real gap — FileValidator's magic-byte check
   confirms a PDF looks like a PDF, it says nothing about whether that
   PDF is malicious. A production deployment accepting uploads from
   untrusted users needs a real scanner (ClamAV via clamd, or a cloud AV
   API) wired in before this gateway is exposed publicly. Nakima has no
   AV integration anywhere in this codebase, and faking one — a function
   called `scan_for_viruses` that doesn't actually scan for viruses —
   would be worse than not having the function at all, since it would
   look like a safety control that isn't one. This is a genuine
   before-production gap, not a "nice to have."

2. Turning extracted_text into structured Project DNA fields (functional
   requirements, constraints, roadmap, business objectives — the
   "Document Intelligence Engine" outputs from the EIP spec). That's a
   CognitiveEngine-shaped problem (extraction is a judgment call, not a
   lookup) that deserves its own prompt design and evaluation, not a
   rushed addition here. This gateway's job ends at "text is extracted
   and stored"; a future increment reads ProjectDocument.extracted_text
   the same way neis/reasoning/decision_engine.py reads
   ProjectRealityModel and UserIntent today.
"""

import hashlib
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from documents.parsers import extract_text
from documents.validators import FileValidator
from models.document import ProjectDocument


@dataclass
class UploadResult:
    document: ProjectDocument
    is_duplicate: bool


class ProjectUploadGateway:
    def __init__(self, session: AsyncSession, repository_id: int):
        self.session = session
        self.repository_id = repository_id
        self.validator = FileValidator()

    async def upload(self, filename: str, content: bytes) -> UploadResult:
        content_hash = hashlib.sha256(content).hexdigest()

        existing = await self._find_by_hash(content_hash)
        if existing is not None:
            return UploadResult(document=existing, is_duplicate=True)

        result = self.validator.validate(filename, content)
        version = await self._next_version()

        if not result.ok:
            doc = ProjectDocument(
                repository_id=self.repository_id,
                filename=filename,
                file_type=result.file_type or "unknown",
                size_bytes=len(content),
                content_hash=content_hash,
                version=version,
                status="rejected",
                rejection_reason=result.reason,
            )
            self.session.add(doc)
            await self.session.commit()
            await self.session.refresh(doc)
            return UploadResult(document=doc, is_duplicate=False)

        extracted_text = extract_text(result.file_type, content)

        doc = ProjectDocument(
            repository_id=self.repository_id,
            filename=filename,
            file_type=result.file_type,
            size_bytes=len(content),
            content_hash=content_hash,
            version=version,
            status="processed",
            extracted_text=extracted_text,
        )
        self.session.add(doc)
        await self.session.commit()
        await self.session.refresh(doc)
        return UploadResult(document=doc, is_duplicate=False)

    async def list_documents(self, limit: int = 50) -> list[ProjectDocument]:
        stmt = (
            select(ProjectDocument)
            .where(ProjectDocument.repository_id == self.repository_id)
            .order_by(ProjectDocument.uploaded_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def _find_by_hash(self, content_hash: str) -> ProjectDocument | None:
        stmt = select(ProjectDocument).where(
            ProjectDocument.repository_id == self.repository_id,
            ProjectDocument.content_hash == content_hash,
            ProjectDocument.status == "processed",
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def _next_version(self) -> int:
        stmt = select(func.max(ProjectDocument.version)).where(
            ProjectDocument.repository_id == self.repository_id
        )
        current_max = (await self.session.execute(stmt)).scalar_one_or_none()
        return (current_max or 0) + 1
