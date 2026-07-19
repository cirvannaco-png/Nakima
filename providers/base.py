from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProviderResponse:
    content: str
    model: str
    usage: dict[str, Any] = field(default_factory=dict)


class AIProvider(ABC):
    @abstractmethod
    async def analyze(self, code: str, context: dict[str, Any]) -> ProviderResponse: ...

    @abstractmethod
    async def plan(self, requirement: str, context: dict[str, Any]) -> ProviderResponse: ...

    @abstractmethod
    async def generate(self, prompt: str, context: dict[str, Any]) -> ProviderResponse: ...

    @abstractmethod
    async def debug(self, error: str, context: dict[str, Any]) -> ProviderResponse: ...

    @abstractmethod
    async def review(self, diff: str, context: dict[str, Any]) -> ProviderResponse: ...

    @abstractmethod
    async def refactor(self, code: str, instructions: str, context: dict[str, Any]) -> ProviderResponse: ...

    @abstractmethod
    async def explain(self, code: str, context: dict[str, Any]) -> ProviderResponse: ...

    @abstractmethod
    async def generate_tests(self, code: str, context: dict[str, Any]) -> ProviderResponse: ...
