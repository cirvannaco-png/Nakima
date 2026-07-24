import os
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

os.environ.setdefault("GITHUB_APP_ID", "123456")
os.environ.setdefault("GITHUB_PRIVATE_KEY", "test-private-key-not-real")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "testsecret")
os.environ.setdefault("GITHUB_TOKEN", "ghp-test")
os.environ.setdefault("DEFAULT_AI_PROVIDER", "github")


@pytest.fixture
async def db_session():
    from database.base import Base
    from models.document import ProjectDocument  # noqa: F401
    from models.graph import GraphEdge, GraphNode  # noqa: F401
    from models.intelligence.decision import EngineeringDecision, EngineeringEvent  # noqa: F401
    from models.knowledge import KnowledgeEdge, KnowledgeNode  # noqa: F401
    from models.neis.evolution_roadmap import EvolutionRoadmap, EvolutionRoadmapItem  # noqa: F401
    from models.neis.project_reality import ProjectRealityModel  # noqa: F401
    from models.neis.technology_intel import TechnologyIntel  # noqa: F401
    from models.neis.user_intent import UserIntent  # noqa: F401
    from models.policy import RepositoryPolicy  # noqa: F401
    from models.report import EngineeringReport  # noqa: F401

    # Import every model so Base.metadata is fully populated before create_all.
    from models.repository import Repository  # noqa: F401
    from models.security import SecurityFinding  # noqa: F401
    from models.task import Task  # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def sample_repo(tmp_path) -> Path:
    (tmp_path / "sample.py").write_text(
        "import os\n"
        "from pathlib import Path\n\n"
        "class Widget:\n"
        "    def __init__(self, name):\n"
        "        self.name = name\n\n"
        "    def render(self):\n"
        '        return f"<widget>{self.name}</widget>"\n\n'
        "def standalone_function(x, y):\n"
        "    return x + y\n"
    )
    (tmp_path / "main.py").write_text(
        'import os\nfrom sample import Widget\n\ndef build_widget():\n    w = Widget("test")\n    return w.render()\n'
    )
    return tmp_path
