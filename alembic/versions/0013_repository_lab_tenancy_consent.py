"""add provider-neutral installation ownership and Lab consent

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
    # A provider installation is the tenant boundary. External IDs are
    # strings so GitHub, GitLab, and other providers share one model.
    op.create_table(
        "provider_installations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("external_installation_id", sa.String(length=255), nullable=False),
        sa.Column("account_external_id", sa.String(length=255), nullable=True),
        sa.Column("account_login", sa.String(length=255), nullable=True),
        sa.Column("account_type", sa.String(length=32), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("deactivated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "provider",
            "external_installation_id",
            name="uq_provider_installations_provider_external_id",
        ),
    )

    # Preserve the existing integer repositories.id and tasks FK as the
    # single canonical repository identity. Existing repositories stay
    # unattached until their provider installation is verified.
    op.add_column(
        "repositories",
        sa.Column("provider_installation_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_repositories_provider_installation_id",
        "repositories",
        "provider_installations",
        ["provider_installation_id"],
        ["id"],
    )
    op.create_index(
        "ix_repositories_provider_installation_id",
        "repositories",
        ["provider_installation_id"],
    )
    op.create_unique_constraint(
        "uq_repositories_id_installation",
        "repositories",
        ["id", "provider_installation_id"],
    )

    # Legacy repositories are opted out. Enabling Lab requires a complete,
    # auditable consent record and an attached provider installation.
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
    op.add_column(
        "repositories",
        sa.Column("sandbox_lab_consent_actor_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "repositories",
        sa.Column("sandbox_lab_consent_version", sa.String(length=64), nullable=True),
    )
    op.create_check_constraint(
        "ck_repositories_lab_consent_complete",
        "repositories",
        "sandbox_lab_opt_in = false OR "
        "(provider_installation_id IS NOT NULL "
        "AND sandbox_lab_consented_at IS NOT NULL "
        "AND sandbox_lab_consent_actor_id IS NOT NULL "
        "AND sandbox_lab_consent_version IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_repositories_lab_consent_complete", "repositories", type_="check")
    op.drop_column("repositories", "sandbox_lab_consent_version")
    op.drop_column("repositories", "sandbox_lab_consent_actor_id")
    op.drop_column("repositories", "sandbox_lab_consented_at")
    op.drop_column("repositories", "sandbox_lab_opt_in")
    op.drop_constraint("uq_repositories_id_installation", "repositories", type_="unique")
    op.drop_index("ix_repositories_provider_installation_id", table_name="repositories")
    op.drop_constraint("fk_repositories_provider_installation_id", "repositories", type_="foreignkey")
    op.drop_column("repositories", "provider_installation_id")
    op.drop_table("provider_installations")
