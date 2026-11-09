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
        sa.Column("repository_id", sa.Integer(), nullable=False),
        sa.Column("provider_installation_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            ondelete="RESTRICT",
            name="fk_sandbox_runs_repository",
        ),
        sa.ForeignKeyConstraint(
            ["provider_installation_id"],
            ["provider_installations.id"],
            ondelete="RESTRICT",
            name="fk_sandbox_runs_provider_installation",
        ),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("source_commit_sha", sa.String(length=64), nullable=False),
        sa.Column("container_id", sa.String(length=128), nullable=True),
        sa.Column("container_image", sa.String(length=255), nullable=True),
        sa.Column("network_isolated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("synthetic_injection_used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("result_schema_version", sa.String(length=32), nullable=True),
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
        sa.CheckConstraint(
            "network_isolated = false OR (container_id IS NOT NULL AND container_image IS NOT NULL)",
            name="ck_sandbox_runs_isolation_evidence",
        ),
    )
    op.execute(
        """
        CREATE FUNCTION enforce_sandbox_run_tenant()
        RETURNS trigger AS $enforce$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM repositories r
                JOIN provider_installations p ON p.id = NEW.provider_installation_id
                WHERE r.id = NEW.repository_id
                  AND r.provider_installation_id = NEW.provider_installation_id
                  AND p.is_active = true
            ) THEN
                RAISE EXCEPTION
                    'sandbox run requires a repository linked to an active provider installation';
            END IF;

            IF NEW.synthetic_injection_used AND NOT EXISTS (
                SELECT 1
                FROM repositories
                WHERE id = NEW.repository_id
                  AND provider_installation_id = NEW.provider_installation_id
                  AND sandbox_lab_opt_in = true
            ) THEN
                RAISE EXCEPTION
                    'synthetic injection requires complete Lab consent for repository %',
                    NEW.repository_id;
            END IF;
            RETURN NEW;
        END;
        $enforce$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_enforce_sandbox_run_tenant
        BEFORE INSERT OR UPDATE OF repository_id, provider_installation_id, synthetic_injection_used
        ON sandbox_runs
        FOR EACH ROW EXECUTE FUNCTION enforce_sandbox_run_tenant();
        """
    )

    op.create_index(
        "ix_sandbox_runs_repository_created",
        "sandbox_runs",
        ["repository_id", "created_at"],
    )
    op.create_index(
        "ix_sandbox_runs_provider_installation_created",
        "sandbox_runs",
        ["provider_installation_id", "created_at"],
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
        sa.Column("reviewed_by", sa.String(length=768), nullable=False),
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
        sa.Column("applied_commit_sha", sa.String(length=64), nullable=True),
        sa.Column("tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("test_results", sa.JSON(), nullable=True),
        sa.Column("judge_reasoning", sa.Text(), nullable=True),
        sa.Column("retained_for_training", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "candidate_status IN ('proposed', 'applied', 'tested', 'rejected', 'selected')",
            name="ck_model_candidate_fixes_status",
        ),
        sa.CheckConstraint(
            "candidate_status NOT IN ('applied', 'tested', 'selected') OR applied_commit_sha IS NOT NULL",
            name="ck_model_candidate_fixes_applied_has_commit",
        ),
        sa.CheckConstraint(
            "candidate_status NOT IN ('tested', 'selected') OR "
            "(test_suite_passed IS NOT NULL AND tested_at IS NOT NULL "
            "AND applied_commit_sha IS NOT NULL AND test_results IS NOT NULL)",
            name="ck_model_candidate_fixes_tested_has_result",
        ),
        sa.CheckConstraint(
            "retained_for_training = false",
            name="ck_model_candidate_fixes_training_retention_disabled",
        ),
        sa.CheckConstraint(
            "candidate_status != 'selected' OR test_suite_passed IS TRUE",
            name="ck_model_candidate_fixes_selected_passed",
        ),
    )
    op.create_index("ix_model_candidate_fixes_run", "model_candidate_fixes", ["sandbox_run_id"])
    op.create_index(
        "uq_model_candidate_fixes_one_selected_per_run",
        "model_candidate_fixes",
        ["sandbox_run_id"],
        unique=True,
        postgresql_where=sa.text("candidate_status = 'selected'"),
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_enforce_sandbox_run_tenant ON sandbox_runs")
    op.execute("DROP FUNCTION IF EXISTS enforce_sandbox_run_tenant()")
    op.drop_index("uq_model_candidate_fixes_one_selected_per_run", table_name="model_candidate_fixes")
    op.drop_table("model_candidate_fixes")
    op.drop_index("ix_run_reviews_run_reviewed", table_name="run_reviews")
    op.drop_table("run_reviews")
    op.drop_index("ix_sandbox_runs_status_expires", table_name="sandbox_runs")
    op.drop_index("ix_sandbox_runs_provider_installation_created", table_name="sandbox_runs")
    op.drop_index("ix_sandbox_runs_repository_created", table_name="sandbox_runs")
    op.drop_table("sandbox_runs")
