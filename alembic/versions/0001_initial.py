"""initial schema: repositories, tasks

Revision ID: 0001
Revises:
Create Date: 2026-07-15
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# postgresql.ENUM(create_type=False) prevents SQLAlchemy from auto-issuing CREATE TYPE inside
# op.create_table(); we control type creation explicitly with checkfirst=True
# so re-running the migration on a database that already has the type is safe.
task_status = postgresql.ENUM("pending", "in_progress", "success", "failed", name="taskstatus", create_type=False)


def upgrade() -> None:
    task_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "repositories",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("full_name", sa.String(200), nullable=False, unique=True, index=True),
        sa.Column("github_repo_id", sa.BigInteger, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "tasks",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("repository_id", sa.Integer, sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("status", task_status, nullable=False, server_default="pending"),
        sa.Column("event_payload", sa.JSON, nullable=True),
        sa.Column("pr_url", sa.String(500), nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("tasks")
    op.drop_table("repositories")
    task_status.drop(op.get_bind(), checkfirst=True)
