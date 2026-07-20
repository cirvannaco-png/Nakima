from typing import Any

from providers.manager import provider_manager

RISK_WORDS = ["migration", "schema", "auth", "authentication", "security", "database", "critical"]


class PlanningEngine:
    def __init__(self, provider_name: str | None = None):
        self.provider = provider_manager.get_provider(provider_name)

    async def create_plan(self, requirement: str, repo_context: dict[str, Any]) -> dict:
        analysis = await self.provider.analyze(
            code=repo_context.get("structure_summary", ""),
            context={"requirement": requirement},
        )
        plan = await self.provider.plan(requirement, repo_context)
        risk = self._estimate_risk(plan.content)

        return {
            "requirement": requirement,
            "affected_files": self._extract_files(plan.content),
            "steps": plan.content,
            "analysis": analysis.content,
            "risk_score": risk,
            "rollback_plan": "Revert the generated commits and delete the feature branch.",
        }

    def _extract_files(self, plan_text: str) -> list[str]:
        files = []
        for line in plan_text.split("\n"):
            stripped = line.strip().strip("`-* ")
            if stripped.endswith((".py", ".js", ".ts", ".go", ".java")):
                files.append(stripped)
        return files

    def _estimate_risk(self, plan_text: str) -> float:
        score = 10.0
        lowered = plan_text.lower()
        for word in RISK_WORDS:
            if word in lowered:
                score += 15
        return min(score, 100)
