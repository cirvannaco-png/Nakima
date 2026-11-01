"""Add screenshot and video evidence to code-change tasks."""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "change_attachments",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("task_id", sa.Uuid(as_uuid=True), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(length=120), nullable=False),
        sa.Column("media_type", sa.String(length=80), nullable=False),
        sa.Column("caption", sa.String(length=300), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_change_attachments_task_id", "change_attachments", ["task_id"])

def downgrade() -> None:
    op.drop_index("ix_change_attachments_task_id", table_name="change_attachments")
    op.drop_table("change_attachments")
