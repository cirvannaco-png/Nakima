import uuid
from unittest.mock import AsyncMock

import pytest

from market_research.judge import JudgeAgent
from market_research.opportunity_engine import OpportunityEngine
from market_research.promotion import OpportunityPromoter
from market_research.research_scout import ResearchScout
from market_research.search import SearchResult
from models.neis.evolution_roadmap import EvolutionRoadmap, RoadmapStatus
from models.neis.external_opportunity import (
    ExternalOpportunity,
    ExternalSignal,
    JudgeVerdict,
    OpportunityStatus,
    SignalSource,
)
from models.repository import Repository
from providers.base import ProviderResponse


async def _make_repo(db_session) -> Repository:
    repo = Repository(full_name="cirvannaco-png/Nakima")
    db_session.add(repo)
    await db_session.flush()
    return repo


# --- ResearchScout -----------------------------------------------------------


class _FakeSearchClient:
    def __init__(self, results: list[SearchResult] | None = None, raise_on: str | None = None):
        self.results = results or []
        self.raise_on = raise_on

    async def search(self, query: str, max_results: int) -> list[SearchResult]:
        if query == self.raise_on:
            raise RuntimeError("search backend unavailable")
        return self.results


async def test_research_scout_persists_signals_per_query(db_session):
    repo = await _make_repo(db_session)
    client = _FakeSearchClient([SearchResult(title="Competitor X launches Y", url="https://x.test", snippet="...")])

    signals = await ResearchScout(db_session, client).scan(repo.id, ["abandoned cart recovery"])

    assert len(signals) == 1
    assert signals[0].source == SignalSource.WEB_SEARCH
    assert signals[0].judge_verdict == JudgeVerdict.PENDING


async def test_research_scout_degrades_one_failing_query_without_failing_others(db_session):
    repo = await _make_repo(db_session)
    client = _FakeSearchClient([SearchResult(title="found it", url="https://x.test", snippet="...")], raise_on="bad")

    signals = await ResearchScout(db_session, client).scan(repo.id, ["bad", "good"])

    assert len(signals) == 1
    assert signals[0].query == "good"


# --- JudgeAgent ---------------------------------------------------------------


async def test_judge_fails_closed_with_no_provider(db_session):
    repo = await _make_repo(db_session)
    signal = ExternalSignal(
        repository_id=repo.id, source=SignalSource.WEB_SEARCH, query="q", title="t", url="u", snippet="s"
    )
    db_session.add(signal)
    await db_session.flush()

    judged = await JudgeAgent(db_session, provider=None).judge_pending(repo.id, "some repo context")

    assert len(judged) == 1
    assert judged[0].judge_verdict == JudgeVerdict.REJECTED
    assert "No AI provider" in judged[0].judge_rationale


async def test_judge_parses_accepted_verdict(db_session):
    repo = await _make_repo(db_session)
    signal = ExternalSignal(
        repository_id=repo.id, source=SignalSource.WEB_SEARCH, query="q", title="t", url="u", snippet="s"
    )
    db_session.add(signal)
    await db_session.flush()

    provider = AsyncMock()
    provider.analyze.return_value = ProviderResponse(
        content="VERDICT: accepted\nRATIONALE: Directly relevant and from a named competitor's own blog.",
        model="test",
    )

    judged = await JudgeAgent(db_session, provider).judge_pending(repo.id, "ctx")

    assert judged[0].judge_verdict == JudgeVerdict.ACCEPTED
    assert "competitor" in judged[0].judge_rationale


async def test_judge_fails_closed_on_malformed_response(db_session):
    repo = await _make_repo(db_session)
    signal = ExternalSignal(
        repository_id=repo.id, source=SignalSource.WEB_SEARCH, query="q", title="t", url="u", snippet="s"
    )
    db_session.add(signal)
    await db_session.flush()

    provider = AsyncMock()
    provider.analyze.return_value = ProviderResponse(content="I think this looks pretty good actually!", model="test")

    judged = await JudgeAgent(db_session, provider).judge_pending(repo.id, "ctx")

    assert judged[0].judge_verdict == JudgeVerdict.REJECTED
    assert "did not follow" in judged[0].judge_rationale


async def test_judge_fails_closed_when_provider_call_raises(db_session):
    repo = await _make_repo(db_session)
    signal = ExternalSignal(
        repository_id=repo.id, source=SignalSource.WEB_SEARCH, query="q", title="t", url="u", snippet="s"
    )
    db_session.add(signal)
    await db_session.flush()

    provider = AsyncMock()
    provider.analyze.side_effect = RuntimeError("provider down")

    judged = await JudgeAgent(db_session, provider).judge_pending(repo.id, "ctx")

    assert judged[0].judge_verdict == JudgeVerdict.REJECTED
    assert "failed" in judged[0].judge_rationale


async def test_judge_only_touches_pending_signals(db_session):
    repo = await _make_repo(db_session)
    already_accepted = ExternalSignal(
        repository_id=repo.id,
        source=SignalSource.WEB_SEARCH,
        query="q",
        title="t",
        url="u",
        snippet="s",
        judge_verdict=JudgeVerdict.ACCEPTED,
        judge_rationale="previously judged",
    )
    db_session.add(already_accepted)
    await db_session.flush()

    judged = await JudgeAgent(db_session, provider=None).judge_pending(repo.id, "ctx")

    assert judged == []  # nothing PENDING — the already-judged row is untouched


# --- OpportunityEngine ---------------------------------------------------------


def _signal(repo_id, verdict=JudgeVerdict.ACCEPTED) -> ExternalSignal:
    return ExternalSignal(
        id=uuid.uuid4(),
        repository_id=repo_id,
        source=SignalSource.WEB_SEARCH,
        query="q",
        title="Competitor ships adaptive recovery",
        url="https://example.test",
        snippet="They personalize timing and channel automatically.",
        judge_verdict=verdict,
    )


async def test_opportunity_engine_ignores_rejected_signals(db_session):
    repo = await _make_repo(db_session)
    provider = AsyncMock()
    opportunities = await OpportunityEngine(db_session, provider).generate(
        repo.id, "ctx", [_signal(repo.id, verdict=JudgeVerdict.REJECTED)]
    )
    assert opportunities == []
    provider.plan.assert_not_called()


async def test_opportunity_engine_returns_nothing_without_provider(db_session):
    repo = await _make_repo(db_session)
    opportunities = await OpportunityEngine(db_session, provider=None).generate(repo.id, "ctx", [_signal(repo.id)])
    assert opportunities == []


async def test_opportunity_engine_parses_valid_json_response(db_session):
    repo = await _make_repo(db_session)
    signal = _signal(repo.id)
    provider = AsyncMock()
    provider.plan.return_value = ProviderResponse(
        content=(
            '[{"title": "Adaptive recovery", "description": "Learn timing/channel per customer.", '
            '"confidence": 6, "signal_indices": [1]}]'
        ),
        model="test",
    )

    opportunities = await OpportunityEngine(db_session, provider).generate(repo.id, "ctx", [signal])

    assert len(opportunities) == 1
    assert opportunities[0].title == "Adaptive recovery"
    assert opportunities[0].confidence == pytest.approx(6.0)
    assert opportunities[0].status == OpportunityStatus.PROPOSED


async def test_opportunity_engine_degrades_on_malformed_json(db_session):
    repo = await _make_repo(db_session)
    provider = AsyncMock()
    provider.plan.return_value = ProviderResponse(content="not json at all", model="test")

    opportunities = await OpportunityEngine(db_session, provider).generate(repo.id, "ctx", [_signal(repo.id)])

    assert opportunities == []


async def test_opportunity_engine_strips_json_code_fence(db_session):
    repo = await _make_repo(db_session)
    provider = AsyncMock()
    provider.plan.return_value = ProviderResponse(
        content='```json\n[{"title": "X", "description": "Y", "confidence": 3, "signal_indices": []}]\n```',
        model="test",
    )

    opportunities = await OpportunityEngine(db_session, provider).generate(repo.id, "ctx", [_signal(repo.id)])
    assert len(opportunities) == 1


async def test_opportunity_engine_skips_malformed_elements_without_failing_batch(db_session):
    repo = await _make_repo(db_session)
    provider = AsyncMock()
    provider.plan.return_value = ProviderResponse(
        content='[{"title": ""}, {"title": "Valid", "description": "Fine", "confidence": 2, "signal_indices": []}]',
        model="test",
    )

    opportunities = await OpportunityEngine(db_session, provider).generate(repo.id, "ctx", [_signal(repo.id)])
    assert len(opportunities) == 1
    assert opportunities[0].title == "Valid"


# --- OpportunityPromoter -------------------------------------------------------


async def test_promote_requires_active_roadmap(db_session):
    repo = await _make_repo(db_session)
    opp = ExternalOpportunity(repository_id=repo.id, title="t", description="d", confidence=5.0)
    db_session.add(opp)
    await db_session.flush()

    with pytest.raises(ValueError, match="No active roadmap"):
        await OpportunityPromoter(db_session).promote(repo.id, opp.id)


async def test_promote_creates_roadmap_item_and_marks_promoted(db_session):
    repo = await _make_repo(db_session)
    roadmap = EvolutionRoadmap(repository_id=repo.id, status=RoadmapStatus.ACTIVE, summary="s")
    db_session.add(roadmap)
    opp = ExternalOpportunity(repository_id=repo.id, title="Adaptive recovery", description="d", confidence=7.0)
    db_session.add(opp)
    await db_session.flush()

    item = await OpportunityPromoter(db_session).promote(repo.id, opp.id)

    assert item.title == "Adaptive recovery"
    assert item.category.value == "market_opportunity"
    await db_session.refresh(opp)
    assert opp.status == OpportunityStatus.PROMOTED
    assert opp.promoted_roadmap_item_id == item.id


async def test_promote_rejects_already_promoted_opportunity(db_session):
    repo = await _make_repo(db_session)
    roadmap = EvolutionRoadmap(repository_id=repo.id, status=RoadmapStatus.ACTIVE, summary="s")
    db_session.add(roadmap)
    opp = ExternalOpportunity(
        repository_id=repo.id, title="t", description="d", confidence=5.0, status=OpportunityStatus.PROMOTED
    )
    db_session.add(opp)
    await db_session.flush()

    with pytest.raises(ValueError, match="not proposed"):
        await OpportunityPromoter(db_session).promote(repo.id, opp.id)


async def test_promote_rejects_unknown_opportunity(db_session):
    repo = await _make_repo(db_session)
    with pytest.raises(ValueError, match="No opportunity"):
        await OpportunityPromoter(db_session).promote(repo.id, uuid.uuid4())


async def test_dismiss_marks_dismissed(db_session):
    repo = await _make_repo(db_session)
    opp = ExternalOpportunity(repository_id=repo.id, title="t", description="d", confidence=5.0)
    db_session.add(opp)
    await db_session.flush()

    dismissed = await OpportunityPromoter(db_session).dismiss(repo.id, opp.id)
    assert dismissed.status == OpportunityStatus.DISMISSED
