"""Engineering Decision Registry — records why an architectural or
implementation decision was made, independent of whether any code has
changed yet. See `models/intelligence/__init__.py` for how this relates
to NEIS.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.intelligence.decision import EngineeringDecision


class DecisionRegistry:
    def __init__(self, session: AsyncSession, repository_id: int):
        self.session = session
        self.repository_id = repository_id

    async def record(
        self,
        *,
        context: str,
        problem: str,
        decision: str,
        justification: str,
        alternatives: list[dict] | None = None,
        consequences: str | None = None,
        related_files: list[str] | None = None,
        related_issues: list[str] | None = None,
        author: str = "nakima",
    ) -> EngineeringDecision:
        row = EngineeringDecision(
            repository_id=self.repository_id,
            context=context,
            problem=problem,
            decision=decision,
            justification=justification,
            alternatives=alternatives or [],
            consequences=consequences,
            related_files=related_files or [],
            related_issues=related_issues or [],
            author=author,
        )
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def list_for_repository(self, limit: int = 50) -> list[EngineeringDecision]:
        stmt = (
            select(EngineeringDecision)
            .where(EngineeringDecision.repository_id == self.repository_id)
            .order_by(EngineeringDecision.created_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get(self, decision_id) -> EngineeringDecision | None:
        return await self.session.get(EngineeringDecision, decision_id)
