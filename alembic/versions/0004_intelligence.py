"""intelligence: engineering decision registry + event log

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "engineering_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("repository_id", sa.Integer, sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("context", sa.Text, nullable=False),
        sa.Column("problem", sa.Text, nullable=False),
        sa.Column("alternatives", sa.JSON, nullable=False),
        sa.Column("decision", sa.Text, nullable=False),
        sa.Column("justification", sa.Text, nullable=False),
        sa.Column("consequences", sa.Text, nullable=True),
        sa.Column("related_files", sa.JSON, nullable=False),
        sa.Column("related_issues", sa.JSON, nullable=False),
        sa.Column("author", sa.String(200), nullable=False, server_default="nakima"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("extra_data", sa.JSON, nullable=True),
    )
    op.create_index("ix_eng_decisions_repository_id", "engineering_decisions", ["repository_id"])
    op.create_index("ix_eng_decisions_created_at", "engineering_decisions", ["created_at"])

    op.create_table(
        "engineering_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("repository_id", sa.Integer, sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasks.id"), nullable=True),
        sa.Column(
            "decision_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("engineering_decisions.id"), nullable=True
        ),
        sa.Column("timestamp", sa.DateTime, nullable=False),
        sa.Column("author", sa.String(200), nullable=False, server_default="nakima"),
        sa.Column("task_description", sa.Text, nullable=False),
        sa.Column("files_modified", sa.JSON, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("alternatives_considered", sa.JSON, nullable=False),
        sa.Column("chosen_solution", sa.Text, nullable=False),
        sa.Column("expected_impact", sa.JSON, nullable=True),
        sa.Column("measured_impact", sa.JSON, nullable=True),
        sa.Column("risk_level", sa.String(20), nullable=False, server_default="unknown"),
        sa.Column("dependencies_affected", sa.JSON, nullable=False),
        sa.Column("tests_executed", sa.JSON, nullable=False),
        sa.Column("verification_status", sa.String(30), nullable=False, server_default="unverified"),
        sa.Column("extra_data", sa.JSON, nullable=True),
    )
    op.create_index("ix_eng_events_repository_id", "engineering_events", ["repository_id"])
    op.create_index("ix_eng_events_task_id", "engineering_events", ["task_id"])
    op.create_index("ix_eng_events_decision_id", "engineering_events", ["decision_id"])
    op.create_index("ix_eng_events_timestamp", "engineering_events", ["timestamp"])


def downgrade() -> None:
    op.drop_table("engineering_events")
    op.drop_table("engineering_decisions")
