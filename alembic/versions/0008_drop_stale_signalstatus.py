"""cleanup: drop stale signalstatus enum type left over from a previous schema

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-30

Background
----------
The `signalstatus` PostgreSQL enum type was created by a previous version of
the application. It is no longer referenced by any table or model in the
current codebase, but its presence in the database caused Alembic/SQLAlchemy
to raise ``DuplicateObjectError`` when any migration attempted to run
``CREATE TYPE`` on a connection that already had it.

This migration is a one-time idempotent cleanup that removes the orphaned
type so the schema matches the current model definitions exactly.
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # DROP TYPE IF EXISTS is safe to run even when the type is absent —
    # useful for fresh databases that never had it.
    op.execute("DROP TYPE IF EXISTS signalstatus")


def downgrade() -> None:
    # Recreate the type with its original values so a rollback to 0007
    # leaves the schema in the same state as before this migration ran.
    op.execute(
        "CREATE TYPE signalstatus AS ENUM "
        "('pending', 'active', 'failed', 'permanently_failed', 'duplicate')"
    )
