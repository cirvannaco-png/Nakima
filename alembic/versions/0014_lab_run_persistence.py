"""add canonical Lab runs, candidate results, and human reviews

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sandbox_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "repository_id",
            sa.Integer(),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("source_commit_sha", sa.String(length=64), nullable=False),
        sa.Column("container_id", sa.String(length=128), nullable=True),
        sa.Column("container_image", sa.String(length=255), nullable=True),
        sa.Column("network_isolated", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("synthetic_injection_used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("diagnosis", sa.JSON(), nullable=True),
        sa.Column("proposed_fix_diff", sa.Text(), nullable=True),
        sa.Column("ai_models_consulted", sa.JSON(), nullable=True),
        sa.Column("full_test_suite_passed", sa.Boolean(), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(now() + interval '24 hours')"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "trigger IN ('ci_failure', 'cve_scan', 'synthetic_injection', 'manual')",
            name="ck_sandbox_runs_trigger",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'provisioning', 'running', 'awaiting_review', "
            "'approved', 'rejected', 'expired', 'failed')",
            name="ck_sandbox_runs_status",
        ),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN "
            "('fix_correct', 'fix_incorrect', 'no_fix_found', 'user_rejected')",
            name="ck_sandbox_runs_outcome",
        ),
        sa.CheckConstraint(
            "synthetic_injection_used = false OR trigger = 'synthetic_injection'",
            name="ck_sandbox_runs_synthetic_trigger",
        ),
    )
    op.create_index(
        "ix_sandbox_runs_repository_created",
        "sandbox_runs",
        ["repository_id", "created_at"],
    )
    op.create_index("ix_sandbox_runs_status_expires", "sandbox_runs", ["status", "expires_at"])

    op.create_table(
        "run_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "sandbox_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sandbox_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reviewed_by", sa.String(length=255), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("decision IN ('approved', 'rejected')", name="ck_run_reviews_decision"),
    )
    op.create_index("ix_run_reviews_run_reviewed", "run_reviews", ["sandbox_run_id", "reviewed_at"])

    op.create_table(
        "model_candidate_fixes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "sandbox_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sandbox_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("candidate_diff", sa.Text(), nullable=False),
        sa.Column("candidate_status", sa.String(length=16), nullable=False, server_default="proposed"),
        sa.Column("test_suite_passed", sa.Boolean(), nullable=True),
        sa.Column("test_results", sa.JSON(), nullable=True),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("judge_reasoning", sa.Text(), nullable=True),
        sa.Column("retained_for_training", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "candidate_status IN ('proposed', 'applied', 'tested', 'rejected', 'selected')",
            name="ck_model_candidate_fixes_status",
        ),
    )
    op.create_index("ix_model_candidate_fixes_run", "model_candidate_fixes", ["sandbox_run_id"])


def downgrade() -> None:
    op.drop_table("model_candidate_fixes")
    op.drop_index("ix_run_reviews_run_reviewed", table_name="run_reviews")
    op.drop_table("run_reviews")
    op.drop_index("ix_sandbox_runs_status_expires", table_name="sandbox_runs")
    op.drop_index("ix_sandbox_runs_repository_created", table_name="sandbox_runs")
    op.drop_table("sandbox_runs")
