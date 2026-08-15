"""add provenance_records table

Revision ID: add_provenance_records
Revises: <fill in your current head revision>
Create Date: 2026-08-15

Copy this into alembic/versions/, rename the file to match Alembic's
convention, and set down_revision to your actual current head
(run `alembic heads` to find it).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provenance_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("record_id", sa.String(64), nullable=False),
        sa.Column("repo", sa.String(255), nullable=False),
        sa.Column("commit_sha", sa.String(64), nullable=True),
        sa.Column("pr_number", sa.Integer, nullable=True),
        sa.Column("file_path", sa.String(1024), nullable=False),
        sa.Column("hunk_hash", sa.String(32), nullable=False),
        sa.Column("contributor_type", sa.String(32), nullable=False),
        sa.Column("agent_name", sa.String(128), nullable=True),
        sa.Column("model_id", sa.String(128), nullable=True),
        sa.Column("issue_ref", sa.String(32), nullable=True),
        sa.Column("prompt_ref", sa.String(255), nullable=True),
        sa.Column("human_actor", sa.String(128), nullable=True),
        sa.Column("accepted_verbatim", sa.Boolean, nullable=True),
        sa.Column("lines_added", sa.Integer, server_default="0"),
        sa.Column("lines_removed", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_provenance_record_id", "provenance_records", ["record_id"])
    op.create_index("ix_provenance_records_repo", "provenance_records", ["repo"])
    op.create_index("ix_provenance_records_commit_sha", "provenance_records", ["commit_sha"])
    op.create_index("ix_provenance_records_pr_number", "provenance_records", ["pr_number"])
    op.create_index("ix_provenance_repo_created", "provenance_records", ["repo", "created_at"])


def downgrade() -> None:
    op.drop_table("provenance_records")
