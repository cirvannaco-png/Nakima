"""documents: project upload gateway

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("repository_id", sa.Integer, sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("file_type", sa.String(20), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("extracted_text", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="processed"),
        sa.Column("virus_scan_status", sa.String(20), nullable=False, server_default="unavailable"),
        sa.Column("rejection_reason", sa.Text, nullable=True),
        sa.Column("uploaded_at", sa.DateTime, nullable=False),
        sa.Column("raw_bytes", sa.LargeBinary, nullable=True),
    )
    op.create_index("ix_project_documents_repository_id", "project_documents", ["repository_id"])
    op.create_index("ix_project_documents_content_hash", "project_documents", ["content_hash"])
    op.create_index("ix_project_documents_uploaded_at", "project_documents", ["uploaded_at"])


def downgrade() -> None:
    op.drop_table("project_documents")
