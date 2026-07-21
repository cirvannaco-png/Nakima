import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class NodeType(str, enum.Enum):
    FILE = "file"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    VARIABLE = "variable"
    IMPORT = "import"
    API_ENDPOINT = "api_endpoint"
    TEST = "test"


class EdgeType(str, enum.Enum):
    IMPORTS = "imports"
    CALLS = "calls"
    INHERITS = "inherits"
    CONTAINS = "contains"
    DEPENDS_ON = "depends_on"
    TESTS = "tests"


class GraphNode(Base):
    __tablename__ = "graph_nodes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    node_type: Mapped[NodeType] = mapped_column(Enum(NodeType))
    name: Mapped[str] = mapped_column(String(500), index=True)
    file_path: Mapped[str | None] = mapped_column(String(1000), nullable=True, index=True)
    line_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # language-specific metadata (decorators, import targets, etc.) — named
    # `properties`, not `metadata`, for the same reason Task.event_payload
    # isn't called `metadata`: it collides with Base.metadata.
    properties: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class GraphEdge(Base):
    __tablename__ = "graph_edges"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("graph_nodes.id"), index=True)
    target_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("graph_nodes.id"), index=True)
    edge_type: Mapped[EdgeType] = mapped_column(Enum(EdgeType))
    properties: Mapped[dict | None] = mapped_column(JSON, nullable=True)
