"""enforce unique external GitHub repository IDs

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-09
"""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Multiple NULL values remain valid for legacy rows. A non-NULL GitHub
    # repository ID can belong to exactly one canonical Nakima repository.
    op.create_unique_constraint(
        "uq_repositories_github_repo_id",
        "repositories",
        ["github_repo_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_repositories_github_repo_id", "repositories", type_="unique")
