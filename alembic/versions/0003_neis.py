"""neis: project reality, technology intel, evolution roadmap, user intent

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-18
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

# postgresql.ENUM(create_type=False) prevents SQLAlchemy from auto-issuing CREATE TYPE inside
# op.create_table(); we control type creation explicitly with checkfirst=True
# so re-running the migration on a database that already has the type is safe.
ecosystem = postgresql.ENUM("pypi", "npm", name="ecosystem", create_type=False)
roadmap_status = postgresql.ENUM("active", "superseded", name="roadmapstatus", create_type=False)
recommendation_category = postgresql.ENUM(
    "dependency", "architecture", "testing", "security", "documentation",
    name="recommendationcategory",
    create_type=False,
)
effort_estimate = postgresql.ENUM("small", "medium", "large", name="effortestimate", create_type=False)
item_status = postgresql.ENUM("proposed", "accepted", "dismissed", "completed", name="itemstatus", create_type=False)


def upgrade() -> None:
    ecosystem.create(op.get_bind(), checkfirst=True)
    roadmap_status.create(op.get_bind(), checkfirst=True)
    recommendation_category.create(op.get_bind(), checkfirst=True)
    effort_estimate.create(op.get_bind(), checkfirst=True)
    item_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "project_reality_models",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("repository_id", sa.Integer, sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("languages", sa.JSON, nullable=False),
        sa.Column("dependencies", sa.JSON, nullable=False),
        sa.Column("loc_by_language", sa.JSON, nullable=False),
        sa.Column("file_count", sa.Integer, nullable=False),
        sa.Column("test_file_count", sa.Integer, nullable=False),
        sa.Column("health_score", sa.Float, nullable=True),
        sa.Column("health_components", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("extra_data", sa.JSON, nullable=True),
    )
    op.create_index("ix_prm_repository_id", "project_reality_models", ["repository_id"])
    op.create_index("ix_prm_created_at", "project_reality_models", ["created_at"])

    op.create_table(
        "technology_intel",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("repository_id", sa.Integer, sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("package_name", sa.String(200), nullable=False),
        sa.Column("ecosystem", ecosystem, nullable=False),
        sa.Column("current_version", sa.String(100), nullable=False),
        sa.Column("latest_version", sa.String(100), nullable=True),
        sa.Column("is_outdated", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("major_versions_behind", sa.Integer, nullable=True),
        sa.Column("scanned_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("repository_id", "package_name", "ecosystem", name="uq_tech_intel_pkg"),
    )
    op.create_index("ix_tech_intel_repository_id", "technology_intel", ["repository_id"])
    op.create_index("ix_tech_intel_package_name", "technology_intel", ["package_name"])

    op.create_table(
        "evolution_roadmaps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("repository_id", sa.Integer, sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("based_on_reality_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("project_reality_models.id"), nullable=True),
        sa.Column("status", roadmap_status, nullable=False, server_default="active"),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("generated_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_roadmaps_repository_id", "evolution_roadmaps", ["repository_id"])
    op.create_index("ix_roadmaps_generated_at", "evolution_roadmaps", ["generated_at"])

    op.create_table(
        "evolution_roadmap_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("roadmap_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("evolution_roadmaps.id"), nullable=False),
        sa.Column("category", recommendation_category, nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("rationale", sa.Text, nullable=False),
        sa.Column("priority_score", sa.Float, nullable=False),
        sa.Column("effort_estimate", effort_estimate, nullable=False),
        sa.Column("status", item_status, nullable=False, server_default="proposed"),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_roadmap_items_roadmap_id", "evolution_roadmap_items", ["roadmap_id"])

    op.create_table(
        "user_intents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("repository_id", sa.Integer, sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("goals", sa.JSON, nullable=False),
        sa.Column("constraints", sa.JSON, nullable=False),
        sa.Column("priority_weights", sa.JSON, nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_user_intents_repository_id", "user_intents", ["repository_id"])
    op.create_index("ix_user_intents_is_active", "user_intents", ["is_active"])


def downgrade() -> None:
    op.drop_table("user_intents")
    op.drop_table("evolution_roadmap_items")
    op.drop_table("evolution_roadmaps")
    op.drop_table("technology_intel")
    op.drop_table("project_reality_models")
    item_status.drop(op.get_bind(), checkfirst=True)
    effort_estimate.drop(op.get_bind(), checkfirst=True)
    recommendation_category.drop(op.get_bind(), checkfirst=True)
    roadmap_status.drop(op.get_bind(), checkfirst=True)
    ecosystem.drop(op.get_bind(), checkfirst=True)
