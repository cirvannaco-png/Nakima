"""The Intent Drift Validator from the EIP spec, and the only class
outside neis/reasoning/ that a caller needs to import. See
neis/reasoning/__init__.py for the full pipeline this coordinates.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.neis.project_reality import ProjectRealityModel
from models.neis.user_intent import UserIntent
from neis.reasoning.arbitration_engine import ArbitrationEngine, ArbitrationResult, DriftVerdict
from neis.reasoning.cognitive_engine import CognitiveAssessment, CognitiveEngine
from neis.reasoning.evidence_engine import EvidenceEngine, IntentConfidenceResult
from providers.manager import provider_manager


@dataclass
class DriftValidationResult:
    arbitration: ArbitrationResult
    intent_confidence: IntentConfidenceResult
    cognitive: CognitiveAssessment

    @property
    def verdict(self) -> DriftVerdict:
        return self.arbitration.verdict

    @property
    def reasoning(self) -> list[str]:
        return self.arbitration.reasoning


class DecisionEngine:
    def __init__(self, session: AsyncSession, repository_id: int):
        self.session = session
        self.repository_id = repository_id
        self._evidence = EvidenceEngine()
        self._cognitive = CognitiveEngine()
        self._arbitration = ArbitrationEngine()

    async def validate(self, proposed_change: dict) -> DriftValidationResult:
        """`proposed_change` is expected to carry whatever a caller has
        at decision time — orchestrator/workflow.py passes
        {"title", "description", "affected_files", "steps"} straight from
        the planner's output, before any code is generated.
        """
        reality = await self._latest_reality()
        intent = await self._active_intent()

        provider = None
        try:
            provider = provider_manager.get_provider()
        except Exception:
            pass  # CognitiveEngine falls back to a neutral judgment

        hard_violations = self._evidence.check_hard_constraints(proposed_change, intent)
        intent_confidence = self._evidence.score_intent_confidence(intent)
        cognitive_assessment = await self._cognitive.assess_alignment(proposed_change, intent, reality, provider)
        arbitration_result = self._arbitration.arbitrate(hard_violations, intent_confidence, cognitive_assessment)

        return DriftValidationResult(
            arbitration=arbitration_result,
            intent_confidence=intent_confidence,
            cognitive=cognitive_assessment,
        )

    async def _latest_reality(self) -> ProjectRealityModel | None:
        stmt = (
            select(ProjectRealityModel)
            .where(ProjectRealityModel.repository_id == self.repository_id)
            .order_by(ProjectRealityModel.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _active_intent(self) -> UserIntent | None:
        stmt = select(UserIntent).where(
            UserIntent.repository_id == self.repository_id,
            UserIntent.is_active.is_(True),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()
