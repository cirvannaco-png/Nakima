"""add canonical GitHub installation and Lab consent to repositories

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-09
"""

from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep the existing integer repositories.id as the sole internal
    # repository identity. Existing records remain unassigned and opted out.
    op.add_column("repositories", sa.Column("github_installation_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "repositories",
        sa.Column(
            "sandbox_lab_opt_in",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column("repositories", sa.Column("sandbox_lab_consented_at", sa.DateTime(), nullable=True))
    op.add_column("repositories", sa.Column("sandbox_lab_consent_actor_id", sa.BigInteger(), nullable=True))
    op.add_column("repositories", sa.Column("sandbox_lab_consent_version", sa.String(length=64), nullable=True))

    op.create_index(
        "ix_repositories_github_installation_id",
        "repositories",
        ["github_installation_id"],
    )
    op.create_check_constraint(
        "ck_repositories_lab_consent_complete",
        "repositories",
        "sandbox_lab_opt_in = false OR "
        "(github_installation_id IS NOT NULL "
        "AND sandbox_lab_consented_at IS NOT NULL "
        "AND sandbox_lab_consent_actor_id IS NOT NULL "
        "AND sandbox_lab_consent_version IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_repositories_lab_consent_complete", "repositories", type_="check")
    op.drop_index("ix_repositories_github_installation_id", table_name="repositories")
    op.drop_column("repositories", "sandbox_lab_consent_version")
    op.drop_column("repositories", "sandbox_lab_consent_actor_id")
    op.drop_column("repositories", "sandbox_lab_consented_at")
    op.drop_column("repositories", "sandbox_lab_opt_in")
    op.drop_column("repositories", "github_installation_id")
