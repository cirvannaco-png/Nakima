"""market research: external signals, opportunities, promotion linkage

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-08
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

signal_source = postgresql.ENUM("web_search", name="signalsource", create_type=False)
judge_verdict = postgresql.ENUM("pending", "accepted", "rejected", name="judgeverdict", create_type=False)
opportunity_status = postgresql.ENUM("proposed", "promoted", "dismissed", name="opportunitystatus", create_type=False)


def upgrade() -> None:
    signal_source.create(op.get_bind(), checkfirst=True)
    judge_verdict.create(op.get_bind(), checkfirst=True)
    opportunity_status.create(op.get_bind(), checkfirst=True)

    # New RecommendationCategory value for market_research/promotion.py.
    # ALTER TYPE ... ADD VALUE cannot run inside the same transaction as a
    # later statement that uses it on some PG versions, but can run inside
    # its own migration transaction fine — no later statement in this file
    # references the new value.
    op.execute("ALTER TYPE recommendationcategory ADD VALUE IF NOT EXISTS 'market_opportunity'")

    op.create_table(
        "external_signals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("repository_id", sa.Integer, sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("source", signal_source, nullable=False),
        sa.Column("query", sa.String(500), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("url", sa.String(2000), nullable=False),
        sa.Column("snippet", sa.Text, nullable=False),
        sa.Column("judge_verdict", judge_verdict, nullable=False, server_default="pending"),
        sa.Column("judge_rationale", sa.Text, nullable=True),
        sa.Column("collected_at", sa.DateTime, nullable=False),
        sa.Column("judged_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_external_signals_repository_id", "external_signals", ["repository_id"])

    op.create_table(
        "external_opportunities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("repository_id", sa.Integer, sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("status", opportunity_status, nullable=False, server_default="proposed"),
        sa.Column(
            "promoted_roadmap_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("evolution_roadmap_items.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_external_opportunities_repository_id", "external_opportunities", ["repository_id"])

    op.create_table(
        "external_opportunity_signals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "opportunity_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("external_opportunities.id"), nullable=False
        ),
        sa.Column("signal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("external_signals.id"), nullable=False),
    )
    op.create_index(
        "ix_external_opportunity_signals_opportunity_id", "external_opportunity_signals", ["opportunity_id"]
    )
    op.create_index("ix_external_opportunity_signals_signal_id", "external_opportunity_signals", ["signal_id"])


def downgrade() -> None:
    op.drop_table("external_opportunity_signals")
    op.drop_table("external_opportunities")
    op.drop_table("external_signals")
    opportunity_status.drop(op.get_bind(), checkfirst=True)
    judge_verdict.drop(op.get_bind(), checkfirst=True)
    signal_source.drop(op.get_bind(), checkfirst=True)
    # market_opportunity enum value is intentionally not removed on
    # downgrade — Postgres has no ALTER TYPE ... DROP VALUE, and any
    # promoted rows using it would need a manual data migration first.
