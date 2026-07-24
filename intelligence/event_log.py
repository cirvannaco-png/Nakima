"""Engineering Event Log — the automatic half of the Engineering
Intelligence Engine. `EventLog.record()` is called from
`orchestrator/workflow.py` at the end of every task (success or failure),
so every automated change Nakima makes leaves a structured trail even if
nobody ever files a manual EngineeringDecision for it.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.intelligence.decision import EngineeringEvent

VALID_RISK_LEVELS = {"low", "medium", "high", "critical", "unknown"}
VALID_VERIFICATION_STATUSES = {"passed", "failed", "partial", "unverified"}


class EventLog:
    def __init__(self, session: AsyncSession, repository_id: int):
        self.session = session
        self.repository_id = repository_id

    async def record(
        self,
        *,
        task_description: str,
        reason: str,
        chosen_solution: str,
        task_id: uuid.UUID | None = None,
        decision_id: uuid.UUID | None = None,
        files_modified: list[str] | None = None,
        alternatives_considered: list[str] | None = None,
        expected_impact: dict | None = None,
        measured_impact: dict | None = None,
        risk_level: str = "unknown",
        dependencies_affected: list[str] | None = None,
        tests_executed: list[str] | None = None,
        verification_status: str = "unverified",
        author: str = "nakima",
    ) -> EngineeringEvent:
        if risk_level not in VALID_RISK_LEVELS:
            raise ValueError(f"risk_level must be one of {sorted(VALID_RISK_LEVELS)}, got {risk_level!r}")
        if verification_status not in VALID_VERIFICATION_STATUSES:
            raise ValueError(
                f"verification_status must be one of {sorted(VALID_VERIFICATION_STATUSES)}, got {verification_status!r}"
            )

        row = EngineeringEvent(
            repository_id=self.repository_id,
            task_id=task_id,
            decision_id=decision_id,
            author=author,
            task_description=task_description,
            files_modified=files_modified or [],
            reason=reason,
            alternatives_considered=alternatives_considered or [],
            chosen_solution=chosen_solution,
            expected_impact=expected_impact,
            measured_impact=measured_impact,
            risk_level=risk_level,
            dependencies_affected=dependencies_affected or [],
            tests_executed=tests_executed or [],
            verification_status=verification_status,
        )
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def list_for_repository(self, limit: int = 50) -> list[EngineeringEvent]:
        stmt = (
            select(EngineeringEvent)
            .where(EngineeringEvent.repository_id == self.repository_id)
            .order_by(EngineeringEvent.timestamp.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_for_task(self, task_id: uuid.UUID) -> list[EngineeringEvent]:
        stmt = select(EngineeringEvent).where(EngineeringEvent.task_id == task_id)
        return list((await self.session.execute(stmt)).scalars().all())
