"""
database/provenance_model.py

Persistent version of core.provenance.ProvenanceRecord. Drop into your
existing database/ package alongside your other models — this assumes
the same Base/session pattern your other models use (adjust the import
on line 14 to match your actual base module, e.g. database.base).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, Index
from sqlalchemy.dialects.postgresql import UUID

from database.base import Base  # adjust to your actual declarative base import


class ProvenanceRecordORM(Base):
    __tablename__ = "provenance_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    record_id = Column(String(64), unique=True, nullable=False, index=True)
    repo = Column(String(255), nullable=False, index=True)
    commit_sha = Column(String(64), nullable=True, index=True)
    pr_number = Column(Integer, nullable=True, index=True)
    file_path = Column(String(1024), nullable=False)
    hunk_hash = Column(String(32), nullable=False)

    contributor_type = Column(String(32), nullable=False)  # ai_agent | human | human_edited_ai
    agent_name = Column(String(128), nullable=True)
    model_id = Column(String(128), nullable=True)
    issue_ref = Column(String(32), nullable=True)
    prompt_ref = Column(String(255), nullable=True)
    human_actor = Column(String(128), nullable=True)
    accepted_verbatim = Column(Boolean, nullable=True)

    lines_added = Column(Integer, default=0)
    lines_removed = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_provenance_repo_created", "repo", "created_at"),
    )

    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "repo": self.repo,
            "commit_sha": self.commit_sha,
            "pr_number": self.pr_number,
            "file_path": self.file_path,
            "hunk_hash": self.hunk_hash,
            "contributor_type": self.contributor_type,
            "agent_name": self.agent_name,
            "model_id": self.model_id,
            "issue_ref": self.issue_ref,
            "prompt_ref": self.prompt_ref,
            "human_actor": self.human_actor,
            "accepted_verbatim": self.accepted_verbatim,
            "lines_added": self.lines_added,
            "lines_removed": self.lines_removed,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
