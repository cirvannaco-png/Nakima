import os
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

os.environ.setdefault("GITHUB_APP_ID", "123456")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "testsecret")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test")


@pytest.fixture
async def db_session():
    from database.base import Base
    # Import every model so Base.metadata is fully populated before create_all.
    from models.repository import Repository  # noqa: F401
    from models.task import Task  # noqa: F401
    from models.graph import GraphNode, GraphEdge  # noqa: F401
    from models.knowledge import KnowledgeNode, KnowledgeEdge  # noqa: F401
    from models.policy import RepositoryPolicy  # noqa: F401

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
        "        return f\"<widget>{self.name}</widget>\"\n\n"
        "def standalone_function(x, y):\n"
        "    return x + y\n"
    )
    (tmp_path / "main.py").write_text(
        "import os\n"
        "from sample import Widget\n\n"
        "def build_widget():\n"
        "    w = Widget(\"test\")\n"
        "    return w.render()\n"
    )
    return tmp_path
