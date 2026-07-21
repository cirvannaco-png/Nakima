"""Project Upload Gateway endpoints. Same repo-lookup and auth posture as
the other endpoint modules — see api/v1/endpoints/intelligence.py.
"""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas import DocumentResponse
from database.session import get_db
from documents.gateway import ProjectUploadGateway
from models.document import ProjectDocument
from models.repository import Repository

router = APIRouter()

_PREVIEW_CHARS = 500


async def _get_repository_or_404(db: AsyncSession, repo_full_name: str) -> Repository:
    result = await db.execute(select(Repository).where(Repository.full_name == repo_full_name))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not indexed yet — POST /repositories/index first")
    return repo


def _to_response(doc: ProjectDocument, is_duplicate: bool = False) -> DocumentResponse:
    preview = None
    if doc.extracted_text:
        preview = doc.extracted_text[:_PREVIEW_CHARS]
        if len(doc.extracted_text) > _PREVIEW_CHARS:
            preview += "…"
    return DocumentResponse(
        id=str(doc.id),
        repository_id=doc.repository_id,
        filename=doc.filename,
        file_type=doc.file_type,
        size_bytes=doc.size_bytes,
        size_kb=round(doc.size_bytes / 1024, 1),
        version=doc.version,
        status=doc.status,
        rejection_reason=doc.rejection_reason,
        extracted_text_preview=preview,
        is_duplicate=is_duplicate,
        sha256=doc.content_hash,          # content_hash IS the sha256 hex digest
        virus_status=doc.virus_scan_status,
        uploaded_at=doc.uploaded_at.isoformat(),
    )


@router.post("/{repo_full_name:path}/upload", response_model=DocumentResponse)
async def upload_document(
    repo_full_name: str,
    file: UploadFile = File(...),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    _MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB hard cap — reading beyond this OOMs the process
    repo = await _get_repository_or_404(db, repo_full_name)
    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(content) // (1024 * 1024)} MB). Maximum allowed size is 50 MB.",
        )
    result = await ProjectUploadGateway(db, repo.id).upload(file.filename or "unnamed", content)
    response = _to_response(result.document, is_duplicate=result.is_duplicate)
    if result.document.status == "rejected":
        raise HTTPException(status_code=422, detail=response.model_dump())
    return response


@router.get("/{repo_full_name:path}", response_model=list[DocumentResponse])
async def list_documents(
    repo_full_name: str,
    db: AsyncSession = Depends(get_db),  # noqa: B008
):
    repo = await _get_repository_or_404(db, repo_full_name)
    docs = await ProjectUploadGateway(db, repo.id).list_documents()
    return [_to_response(d) for d in docs]
