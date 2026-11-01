"""Screenshot/video evidence upload for pending code-change tasks."""
import hashlib,uuid
from fastapi import APIRouter,Depends,File,Form,HTTPException,UploadFile
from pydantic import BaseModel
from sqlalchemy import func,select
from sqlalchemy.ext.asyncio import AsyncSession
from attachments.validation import inspect_media_upload
from database.session import get_db
from models.change_attachment import ChangeAttachment
from models.task import Task,TaskStatus
router=APIRouter()
MAX_FILE=20*1024*1024
class AttachmentResponse(BaseModel):
    id:str;task_id:str;filename:str;media_type:str;caption:str|None;size_bytes:int;sha256:str;created_at:str
def serialize(x):
    return AttachmentResponse(id=str(x.id),task_id=str(x.task_id),filename=x.filename,media_type=x.media_type,caption=x.caption,size_bytes=x.size_bytes,sha256=x.sha256,created_at=x.created_at.isoformat())
@router.post("/{task_id}",response_model=AttachmentResponse,status_code=201)
async def upload(task_id:uuid.UUID,file:UploadFile=File(...),caption:str|None=Form(default=None),db:AsyncSession=Depends(get_db)):
    task=await db.get(Task,task_id)
    if task is None:raise HTTPException(404,"Task not found")
    if task.status!=TaskStatus.PENDING:raise HTTPException(409,"Evidence can only be attached to pending tasks")
    count=await db.scalar(select(func.count()).select_from(ChangeAttachment).where(ChangeAttachment.task_id==task_id))
    if (count or 0)>=10:raise HTTPException(413,"Maximum 10 attachments per task")
    data=await file.read(MAX_FILE+1)
    if len(data)>MAX_FILE:raise HTTPException(413,"Each attachment must be 20 MiB or smaller")
    try:name,mime=inspect_media_upload(file.filename or "attachment",data,file.content_type)
    except ValueError as exc:raise HTTPException(415,str(exc)) from exc
    total=await db.scalar(select(func.coalesce(func.sum(ChangeAttachment.size_bytes),0)).where(ChangeAttachment.task_id==task_id))
    if int(total or 0)+len(data)>40*1024*1024:raise HTTPException(413,"Maximum 40 MiB evidence per task")
    item=ChangeAttachment(task_id=task_id,filename=name,media_type=mime,caption=(caption or "").strip()[:300] or None,size_bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),content=data)
    db.add(item);await db.commit();await db.refresh(item);return serialize(item)
@router.get("/{task_id}",response_model=list[AttachmentResponse])
async def list_for_task(task_id:uuid.UUID,db:AsyncSession=Depends(get_db)):
    if await db.get(Task,task_id) is None:raise HTTPException(404,"Task not found")
    result=await db.execute(select(ChangeAttachment).where(ChangeAttachment.task_id==task_id).order_by(ChangeAttachment.created_at))
    return [serialize(x) for x in result.scalars().all()]
