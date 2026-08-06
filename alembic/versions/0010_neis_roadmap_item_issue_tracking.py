"""neis: add issue_number/issue_url to evolution_roadmap_items

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-06

Supports PATCH /api/v1/neis/{repo}/roadmap/items/{item_id}: accepting an
item can now open a GitHub issue via githubapp/auth.py's installation
token flow, and these two nullable columns record the result. issue_number
also serves as the idempotency check that stops a second accept call on
the same item from opening a duplicate issue — see
api/v1/endpoints/neis.py:update_roadmap_item_status.

Both columns are nullable with no default and no backfill needed: every
existing row predates this feature and simply has no issue yet, which is
exactly what NULL means here.
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("evolution_roadmap_items", sa.Column("issue_number", sa.Integer(), nullable=True))
    op.add_column("evolution_roadmap_items", sa.Column("issue_url", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("evolution_roadmap_items", "issue_url")
    op.drop_column("evolution_roadmap_items", "issue_number")
