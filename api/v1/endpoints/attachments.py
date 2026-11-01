"""Upload and list screenshot/video evidence for pending change requests."""
import hashlib
import uuid
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from attachments.validation import inspect_media_upload
from database.session import get_db
from models.change_attachment import ChangeAttachment
from models.task import Task, TaskStatus

router = APIRouter()
_MAX_FILE_BYTES = 20 * 1024 * 1024
_MAX_TASK_BYTES = 40 * 1024 * 1024
_MAX_FILES_PER_TASK = 10

class AttachmentResponse(BaseModel):
    id: str
    task_id: str
    filename: str
    media_type: str
    caption: str | None
    size_bytes: int
    sha256: str
    created_at: str

def _to_response(item: ChangeAttachment) -> AttachmentResponse:
    return AttachmentResponse(id=str(item.id), task_id=str(item.task_id), filename=item.filename, media_type=item.media_type, caption=item.caption, size_bytes=item.size_bytes, sha256=item.sha256, created_at=item.created_at.isoformat())

@router.post("/{task_id}", response_model=AttachmentResponse, status_code=201)
async def upload_attachment(task_id: uuid.UUID, file: UploadFile = File(...), caption: str | None = Form(default=None), db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != TaskStatus.PENDING:
        raise HTTPException(status_code=409, detail="Attachments can only be added before a task starts")
    count = await db.scalar(select(func.count()).select_from(ChangeAttachment).where(ChangeAttachment.task_id == task_id))
    if (count or 0) >= _MAX_FILES_PER_TASK:
        raise HTTPException(status_code=413, detail=f"A task may contain at most {_MAX_FILES_PER_TASK} attachments")
    content = await file.read(_MAX_FILE_BYTES + 1)
    if len(content) > _MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="Each attachment must be 20 MiB or smaller")
    try:
        safe_name, media_type = inspect_media_upload(file.filename or "attachment", content, file.content_type)
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    current_bytes = await db.scalar(select(func.coalesce(func.sum(ChangeAttachment.size_bytes), 0)).where(ChangeAttachment.task_id == task_id))
    if int(current_bytes or 0) + len(content) > _MAX_TASK_BYTES:
        raise HTTPException(status_code=413, detail="A task may contain at most 40 MiB of media evidence")
    item = ChangeAttachment(task_id=task_id, filename=safe_name, media_type=media_type, caption=(caption or "").strip()[:300] or None, size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest(), content=content)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _to_response(item)

@router.get("/{task_id}", response_model=list[AttachmentResponse])
async def list_attachments(task_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    if await db.get(Task, task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found")
    result = await db.execute(select(ChangeAttachment).where(ChangeAttachment.task_id == task_id).order_by(ChangeAttachment.created_at))
    return [_to_response(item) for item in result.scalars().all()]
