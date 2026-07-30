"""v2: graph, knowledge, policy tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-16
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# create_type=False prevents SQLAlchemy from auto-issuing CREATE TYPE inside
# op.create_table(); we control type creation explicitly with checkfirst=True
# so re-running the migration on a database that already has the type is safe.
node_type = sa.Enum(
    "file", "class", "function", "method", "variable", "import", "api_endpoint", "test",
    name="nodetype",
    create_type=False,
)
edge_type = sa.Enum(
    "imports", "calls", "inherits", "contains", "depends_on", "tests",
    name="edgetype",
    create_type=False,
)


def upgrade() -> None:
    node_type.create(op.get_bind(), checkfirst=True)
    edge_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "graph_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("repository_id", sa.Integer, sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("node_type", node_type, nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("file_path", sa.String(1000), nullable=True),
        sa.Column("line_start", sa.Integer, nullable=True),
        sa.Column("line_end", sa.Integer, nullable=True),
        sa.Column("properties", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_graph_nodes_repository_id", "graph_nodes", ["repository_id"])
    op.create_index("ix_graph_nodes_name", "graph_nodes", ["name"])
    op.create_index("ix_graph_nodes_file_path", "graph_nodes", ["file_path"])

    op.create_table(
        "graph_edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("graph_nodes.id"), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("graph_nodes.id"), nullable=False),
        sa.Column("edge_type", edge_type, nullable=False),
        sa.Column("properties", sa.JSON, nullable=True),
    )
    op.create_index("ix_graph_edges_source_id", "graph_edges", ["source_id"])
    op.create_index("ix_graph_edges_target_id", "graph_edges", ["target_id"])

    op.create_table(
        "knowledge_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("repository_id", sa.Integer, sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("node_type", sa.String(50), nullable=False),
        sa.Column("external_id", sa.String(200), nullable=True),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("extra_data", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_knowledge_nodes_repository_id", "knowledge_nodes", ["repository_id"])
    op.create_index("ix_knowledge_nodes_node_type", "knowledge_nodes", ["node_type"])

    op.create_table(
        "knowledge_edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("knowledge_nodes.id"), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("knowledge_nodes.id"), nullable=False),
        sa.Column("relation", sa.String(50), nullable=False),
        sa.Column("extra_data", sa.JSON, nullable=True),
    )
    op.create_index("ix_knowledge_edges_source_id", "knowledge_edges", ["source_id"])
    op.create_index("ix_knowledge_edges_target_id", "knowledge_edges", ["target_id"])

    op.create_table(
        "repository_policies",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("repository_id", sa.Integer, sa.ForeignKey("repositories.id"), nullable=False, unique=True),
        sa.Column("branch_pattern", sa.String(100), nullable=True),
        sa.Column("required_checks", sa.JSON, nullable=True),
        sa.Column("required_reviewers", sa.JSON, nullable=True),
        sa.Column("require_docstrings", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("require_license", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("review_required", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("additional_rules", sa.JSON, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("repository_policies")
    op.drop_table("knowledge_edges")
    op.drop_table("knowledge_nodes")
    op.drop_table("graph_edges")
    op.drop_table("graph_nodes")
    edge_type.drop(op.get_bind(), checkfirst=True)
    node_type.drop(op.get_bind(), checkfirst=True)
