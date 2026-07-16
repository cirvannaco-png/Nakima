import importlib
import logging
from typing import Dict, Type

from core.config import settings
from providers.base import AIProvider

logger = logging.getLogger(__name__)


class ProviderManager:
    def __init__(self):
        self._providers: Dict[str, Type[AIProvider]] = {}
        self._instances: Dict[str, AIProvider] = {}
        self._load_providers()

    def _load_providers(self):
        provider_map = {
            "claude": "providers.implementations.claude.ClaudeProvider",
            # codex, copilot, deepseek, replit follow the same AIProvider
            # interface as ClaudeProvider — add their modules here once
            # implemented; unimplemented providers are skipped with a warning
            # rather than crashing the whole manager.
        }
        for name, class_path in provider_map.items():
            try:
                module_path, class_name = class_path.rsplit(".", 1)
                module = importlib.import_module(module_path)
                self._providers[name] = getattr(module, class_name)
            except Exception as e:
                logger.warning(f"Provider '{name}' not available: {e}")

    def get_provider(self, name: str | None = None) -> AIProvider:
        provider_name = name or settings.DEFAULT_AI_PROVIDER
        if provider_name not in self._instances:
            if provider_name not in self._providers:
                raise ValueError(
                    f"Unknown or unavailable provider: {provider_name}. "
                    f"Available: {list(self._providers.keys())}"
                )
            self._instances[provider_name] = self._providers[provider_name]()
        return self._instances[provider_name]

    @property
    def available_providers(self) -> list:
        return list(self._providers.keys())


provider_manager = ProviderManager()
