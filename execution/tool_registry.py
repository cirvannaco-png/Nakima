from typing import Dict, List


class ToolRegistry:
    """Maps languages to formatters, linters, build tools, test runners,
    and security scanners. Extend by adding a language key — everything
    else (ValidationPipeline, the sandbox Dockerfile) reads from here."""

    registry: Dict[str, Dict[str, List[str]]] = {
        "python": {
            "format": ["black --check ."],
            "lint": ["flake8 ."],
            "build": ["pip install -e . --break-system-packages"],
            "test": ["pytest -x"],
            "security": ["bandit -r . -q", "safety check"],
        },
        "javascript": {
            "format": ["prettier --check ."],
            "lint": ["eslint ."],
            "build": ["npm install"],
            "test": ["npm test"],
            "security": ["npm audit --audit-level=high"],
        },
        "typescript": {
            "format": ["prettier --check ."],
            "lint": ["eslint . --ext .ts,.tsx"],
            "build": ["npm install && npx tsc --noEmit"],
            "test": ["npm test"],
            "security": ["npm audit --audit-level=high"],
        },
        "go": {
            "format": ["gofmt -l ."],
            "lint": ["golangci-lint run"],
            "build": ["go build ./..."],
            "test": ["go test ./..."],
            "security": ["gosec ./..."],
        },
    }

    @classmethod
    def get_commands(cls, language: str, stage: str) -> List[str]:
        return cls.registry.get(language, {}).get(stage, [])

    @classmethod
    def stages_for(cls, language: str) -> List[str]:
        return list(cls.registry.get(language, {}).keys())

    @classmethod
    def supported_languages(cls) -> List[str]:
        return list(cls.registry.keys())
