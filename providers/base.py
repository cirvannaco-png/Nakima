from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class ProviderResponse:
    content: str
    model: str
    usage: Dict[str, Any] = field(default_factory=dict)


class AIProvider(ABC):
    @abstractmethod
    async def analyze(self, code: str, context: Dict[str, Any]) -> ProviderResponse: ...

    @abstractmethod
    async def plan(self, requirement: str, context: Dict[str, Any]) -> ProviderResponse: ...

    @abstractmethod
    async def generate(self, prompt: str, context: Dict[str, Any]) -> ProviderResponse: ...

    @abstractmethod
    async def debug(self, error: str, context: Dict[str, Any]) -> ProviderResponse: ...

    @abstractmethod
    async def review(self, diff: str, context: Dict[str, Any]) -> ProviderResponse: ...

    @abstractmethod
    async def refactor(self, code: str, instructions: str, context: Dict[str, Any]) -> ProviderResponse: ...

    @abstractmethod
    async def explain(self, code: str, context: Dict[str, Any]) -> ProviderResponse: ...

    @abstractmethod
    async def generate_tests(self, code: str, context: Dict[str, Any]) -> ProviderResponse: ...
