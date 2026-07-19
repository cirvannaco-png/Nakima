import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from core.config import settings
from database.base import Base
from models.graph import GraphEdge, GraphNode  # noqa: F401
from models.knowledge import KnowledgeEdge, KnowledgeNode  # noqa: F401
from models.neis.evolution_roadmap import EvolutionRoadmap, EvolutionRoadmapItem  # noqa: F401
from models.neis.project_reality import ProjectRealityModel  # noqa: F401
from models.neis.technology_intel import TechnologyIntel  # noqa: F401
from models.neis.user_intent import UserIntent  # noqa: F401
from models.policy import RepositoryPolicy  # noqa: F401

# Import all models so Base.metadata is fully populated for autogenerate.
from models.repository import Repository  # noqa: F401
from models.task import Task  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
