"""Repository-scoped CI/CD profile API."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from cicd.profile import CICDProfile, render_pipeline
from database.session import get_db
from models.policy import RepositoryPolicy
from models.repository import Repository

router = APIRouter()
class CICDProfileRequest(BaseModel):
    profile: CICDProfile
    note: str | None = None

async def _get_repo(db: AsyncSession, full_name: str) -> Repository:
    result = await db.execute(select(Repository).where(Repository.full_name == full_name))
    repo = result.scalar_one_or_none()
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not indexed")
    return repo

async def _get_policy(db: AsyncSession, repo_id: int) -> RepositoryPolicy | None:
    result = await db.execute(select(RepositoryPolicy).where(RepositoryPolicy.repository_id == repo_id))
    return result.scalar_one_or_none()

@router.get("/{repo_full_name:path}/profile")
async def get_profile(repo_full_name: str, db: AsyncSession = Depends(get_db)):
    repo = await _get_repo(db, repo_full_name)
    policy = await _get_policy(db, repo.id)
    stored = (policy.additional_rules or {}).get("cicd_profile") if policy else None
    return {"repository": repo.full_name, "profile": CICDProfile.model_validate(stored or {}).model_dump(), "deployment_requires_approval": True}

@router.put("/{repo_full_name:path}/profile")
async def save_profile(repo_full_name: str, req: CICDProfileRequest, db: AsyncSession = Depends(get_db)):
    repo = await _get_repo(db, repo_full_name)
    policy = await _get_policy(db, repo.id)
    if policy is None:
        policy = RepositoryPolicy(repository_id=repo.id, additional_rules={})
        db.add(policy)
    rules = dict(policy.additional_rules or {})
    rules["cicd_profile"] = req.profile.model_dump(mode="json")
    rules["cicd_profile_note"] = (req.note or "")[:500]
    policy.additional_rules = rules
    await db.commit()
    return {"repository": repo.full_name, "profile": req.profile.model_dump(), "saved": True}

@router.post("/{repo_full_name:path}/render")
async def render_profile(repo_full_name: str, db: AsyncSession = Depends(get_db)):
    repo = await _get_repo(db, repo_full_name)
    policy = await _get_policy(db, repo.id)
    stored = (policy.additional_rules or {}).get("cicd_profile") if policy else None
    rendered = render_pipeline(CICDProfile.model_validate(stored or {}))
    return {"repository": repo.full_name, **rendered, "deployment": {"executed": False, "requires_approval": True}}
