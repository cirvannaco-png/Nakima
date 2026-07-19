"""nsil: security findings

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "security_findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("repository_id", sa.Integer, sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("rule", sa.String(200), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("file_path", sa.String(1000), nullable=False),
        sa.Column("line_number", sa.Integer, nullable=True),
        sa.Column("detail", sa.Text, nullable=False),
        sa.Column("fingerprint", sa.String(32), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("first_seen_at", sa.DateTime, nullable=False),
        sa.Column("last_seen_at", sa.DateTime, nullable=False),
        sa.Column("resolved_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_sec_findings_repository_id", "security_findings", ["repository_id"])
    op.create_index("ix_sec_findings_source", "security_findings", ["source"])
    op.create_index("ix_sec_findings_fingerprint", "security_findings", ["fingerprint"])
    op.create_index("ix_sec_findings_status", "security_findings", ["status"])


def downgrade() -> None:
    op.drop_table("security_findings")
