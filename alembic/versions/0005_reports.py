"""reports: engineering intelligence report metadata

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "engineering_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("repository_id", sa.Integer, sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("file_path", sa.String(1000), nullable=False),
        sa.Column("executive_summary", sa.Text, nullable=False),
        sa.Column("sections_included", sa.JSON, nullable=False),
        sa.Column("generated_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_eng_reports_repository_id", "engineering_reports", ["repository_id"])
    op.create_index("ix_eng_reports_generated_at", "engineering_reports", ["generated_at"])


def downgrade() -> None:
    op.drop_table("engineering_reports")
