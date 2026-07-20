"""Agent registry — a single source of truth for every agent class in the
`agents/` package. Import from here instead of importing agent classes
directly so callers don't need to know the module layout.

Usage::

    from agents import AGENT_REGISTRY, get_agent

    cls = AGENT_REGISTRY["analysis"]   # look up by name
    agent = get_agent("analysis")       # construct an instance
    capabilities = list(AGENT_REGISTRY) # enumerate available agents

The registry is intentionally flat — one name per concrete agent class.
Abstract base classes (BaseAgent) are excluded.
"""

from agents.analysis import AnalysisAgent
from agents.debug import DebugAgent
from agents.documentation import DocumentationAgent
from agents.implementation import ImplementationAgent
from agents.refactoring import RefactoringAgent
from agents.security_agent import SecurityAgent
from agents.testing import TestingAgent

# Map capability name → agent class.
AGENT_REGISTRY: dict[str, type] = {
    "analysis": AnalysisAgent,
    "debug": DebugAgent,
    "documentation": DocumentationAgent,
    "implementation": ImplementationAgent,
    "refactoring": RefactoringAgent,
    "security": SecurityAgent,
    "testing": TestingAgent,
}


def get_agent(name: str):
    """Construct and return a new instance of the named agent.

    Raises KeyError with a descriptive message when `name` is not registered,
    so callers get a clear error instead of an AttributeError deep in the stack.
    """
    cls = AGENT_REGISTRY.get(name)
    if cls is None:
        available = ", ".join(sorted(AGENT_REGISTRY))
        raise KeyError(f"Unknown agent {name!r}. Available agents: {available}")
    return cls()


__all__ = ["AGENT_REGISTRY", "get_agent"]
