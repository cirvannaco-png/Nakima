"""enforce unique external GitHub repository IDs

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
    # Fail with a clear remediation path instead of attempting to silently
    # merge or delete repository records if historical data is inconsistent.
    duplicates = op.get_bind().execute(
        sa.text(
            "SELECT github_repo_id FROM repositories "
            "WHERE github_repo_id IS NOT NULL "
            "GROUP BY github_repo_id HAVING COUNT(*) > 1"
        )
    ).scalars().all()
    if duplicates:
        raise RuntimeError(
            "Cannot enforce unique GitHub repository IDs; reconcile duplicate "
            f"repositories.github_repo_id values first: {duplicates}"
        )

    # Multiple NULL values remain valid for legacy rows. A non-NULL GitHub
    # repository ID can belong to exactly one canonical Nakima repository.
    op.create_unique_constraint(
        "uq_repositories_github_repo_id",
        "repositories",
        ["github_repo_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_repositories_github_repo_id", "repositories", type_="unique")
