"""The Project Upload Gateway orchestrator: validate -> virus scan ->
extract text -> duplicate check -> version -> persist.

Virus scanning (security/virus_scanner.py) runs a real ClamAV clamd check
via VirusScanner.scan(). If clamd isn't configured or isn't reachable,
the scan status is recorded as "unavailable" and the upload proceeds
anyway (fail-open) — see virus_scanner.py's docstring for why that's the
right default rather than rejecting every upload the moment this code
ships, before any operator has deployed clamd. What matters is that
ProjectDocument.virus_scan_status always reflects what actually happened
— "unavailable" is never silently reported as "clean".

One thing still explicitly out of scope: turning extracted_text into
structured Project DNA fields (functional requirements, constraints,
roadmap, business objectives — the "Document Intelligence Engine"
outputs from the EIP spec). That's a CognitiveEngine-shaped problem
(extraction is a judgment call, not a lookup) that deserves its own
prompt design and evaluation, not a rushed addition here. This gateway's
job ends at "text is extracted and stored"; a future increment reads
ProjectDocument.extracted_text the same way
neis/reasoning/decision_engine.py reads ProjectRealityModel and
UserIntent today.
"""

import hashlib
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from documents.parsers import extract_text
from documents.validators import FileValidator
from models.document import ProjectDocument
from security.virus_scanner import VirusScanner


@dataclass
class UploadResult:
    document: ProjectDocument
    is_duplicate: bool


class ProjectUploadGateway:
    def __init__(self, session: AsyncSession, repository_id: int):
        self.session = session
        self.repository_id = repository_id
        self.validator = FileValidator()
        self.virus_scanner = VirusScanner()

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
                virus_scan_status="unavailable",  # never scanned — rejected on format grounds first
            )
            self.session.add(doc)
            await self.session.commit()
            await self.session.refresh(doc)
            return UploadResult(document=doc, is_duplicate=False)

        virus_result = self.virus_scanner.scan(content)
        if virus_result.status == "infected":
            doc = ProjectDocument(
                repository_id=self.repository_id,
                filename=filename,
                file_type=result.file_type,
                size_bytes=len(content),
                content_hash=content_hash,
                version=version,
                status="rejected",
                rejection_reason=f"Virus scan flagged this file: {virus_result.threat_name}",
                virus_scan_status="infected",
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
            virus_scan_status=virus_result.status,  # "clean" | "unavailable" | "error"
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
        stmt = select(func.max(ProjectDocument.version)).where(ProjectDocument.repository_id == self.repository_id)
        current_max = (await self.session.execute(stmt)).scalar_one_or_none()
        return (current_max or 0) + 1
