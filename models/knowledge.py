import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class KnowledgeNode(Base):
    __tablename__ = "knowledge_nodes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    # issue, pr, commit, review, convention, failure, fix
    node_type: Mapped[str] = mapped_column(String(50), index=True)
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    summary: Mapped[str] = mapped_column(Text)
    # Renamed from `metadata` -> `extra_data`. Same reserved-name collision
    # as Task.event_payload: `metadata` is Base.metadata on every SQLAlchemy
    # declarative model and can't be reused as a column name.
    extra_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class KnowledgeEdge(Base):
    __tablename__ = "knowledge_edges"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_nodes.id"), index=True)
    target_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_nodes.id"), index=True)
    # fixes, affects, relates_to, etc.
    relation: Mapped[str] = mapped_column(String(50))
    extra_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
