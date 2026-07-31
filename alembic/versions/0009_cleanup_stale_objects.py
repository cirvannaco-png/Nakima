"""cleanup: drop stale tables and enum types from a previous schema version

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-31

Background
----------
An earlier version of this application used ``trade_events`` and ``signals``
tables along with their associated enum types (``tradeeventtype``,
``tradeeventstatus``).  Those tables and types were removed from the current
schema but may still exist in databases that were migrated from that earlier
version.  Their presence causes ``DuplicateObjectError`` when alembic tries
to create any overlapping type, and leaves orphaned objects that confuse
``alembic check`` / autogenerate.

All four statements use ``IF EXISTS`` so this migration is safe to run
against a fresh database that never had those objects.
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop tables first (they depend on the enum types below).
    # CASCADE ensures any foreign-key dependents are removed too.
    op.execute("DROP TABLE IF EXISTS trade_events CASCADE")
    op.execute("DROP TABLE IF EXISTS signals CASCADE")

    # Drop the orphaned enum types.
    op.execute("DROP TYPE IF EXISTS tradeeventtype")
    op.execute("DROP TYPE IF EXISTS tradeeventstatus")

    # signalstatus was already removed by migration 0008; this is a
    # belt-and-suspenders guard for databases that skipped that migration.
    op.execute("DROP TYPE IF EXISTS signalstatus")


def downgrade() -> None:
    # These objects belonged to a removed subsystem; there is no meaningful
    # way to restore them without also restoring the code that used them.
    # A downgrade to 0008 leaves the database in a clean, consistent state.
    pass
