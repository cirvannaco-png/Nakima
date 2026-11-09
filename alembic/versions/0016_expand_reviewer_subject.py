"""expand durable OIDC reviewer subject storage

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-09
"""

from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "run_reviews",
        "reviewed_by",
        existing_type=sa.String(length=255),
        type_=sa.String(length=768),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "run_reviews",
        "reviewed_by",
        existing_type=sa.String(length=768),
        type_=sa.String(length=255),
        existing_nullable=False,
    )
