"""add explicit OIDC principal membership per provider installation

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-09
"""

from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_installation_memberships",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider_installation_id", sa.Integer(), nullable=False),
        sa.Column("principal_issuer", sa.String(length=512), nullable=False),
        sa.Column("principal_subject", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("granted_by_issuer", sa.String(length=512), nullable=False),
        sa.Column("granted_by_subject", sa.String(length=255), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_by_issuer", sa.String(length=512), nullable=True),
        sa.Column("revoked_by_subject", sa.String(length=255), nullable=True),
        sa.Column("revocation_reason", sa.String(length=64), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["provider_installation_id"],
            ["provider_installations.id"],
            ondelete="RESTRICT",
            name="fk_installation_membership_provider_installation",
        ),
        sa.CheckConstraint(
            "role IN ('owner', 'admin', 'maintainer', 'reviewer', 'viewer')",
            name="ck_installation_membership_role",
        ),
        sa.CheckConstraint(
            "length(principal_issuer) > 0 AND length(principal_subject) > 0",
            name="ck_installation_membership_principal",
        ),
        sa.CheckConstraint(
            "is_active = true OR (revoked_at IS NOT NULL AND "
            "revoked_by_issuer IS NOT NULL AND revoked_by_subject IS NOT NULL "
            "AND revocation_reason IS NOT NULL)",
            name="ck_installation_membership_revocation_audit",
        ),
    )
    op.create_index(
        "ix_installation_membership_active_role",
        "provider_installation_memberships",
        ["provider_installation_id", "is_active", "role"],
    )
    op.create_index(
        "uq_installation_membership_active_principal",
        "provider_installation_memberships",
        ["provider_installation_id", "principal_issuer", "principal_subject"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
        sqlite_where=sa.text("is_active = 1"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_installation_membership_active_principal",
        table_name="provider_installation_memberships",
    )
    op.drop_index(
        "ix_installation_membership_active_role",
        table_name="provider_installation_memberships",
    )
    op.drop_table("provider_installation_memberships")
