from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from providers.base import AIProvider
from providers.manager import provider_manager


@dataclass
class AgentRequest:
    action: str
    context: dict[str, Any] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResponse:
    success: bool
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class BaseAgent(ABC):
    def __init__(self, provider_name: str | None = None):
        self.provider: AIProvider = provider_manager.get_provider(provider_name)

    @abstractmethod
    async def execute(self, request: AgentRequest) -> AgentResponse: ...
