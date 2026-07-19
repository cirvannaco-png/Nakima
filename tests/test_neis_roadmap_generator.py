from models.neis.evolution_roadmap import EffortEstimate, RecommendationCategory, RoadmapStatus
from models.repository import Repository
from neis.services.roadmap_generator import RoadmapGenerator


async def _make_repo(db_session):
    repo = Repository(full_name="kelson/test-repo")
    db_session.add(repo)
    await db_session.commit()
    await db_session.refresh(repo)
    return repo


def _rec(title: str, score: float) -> dict:
    return {
        "category": RecommendationCategory.DEPENDENCY,
        "title": title,
        "rationale": "because",
        "priority_score": score,
        "effort_estimate": EffortEstimate.SMALL,
    }


async def test_build_persists_roadmap_and_items_sorted_by_priority(db_session):
    repo = await _make_repo(db_session)
    recs = [_rec("low", 1.0), _rec("high", 9.0), _rec("mid", 5.0)]

    roadmap = await RoadmapGenerator(db_session).build(repo.id, None, recs, "test summary")

    assert roadmap.status == RoadmapStatus.ACTIVE
    assert [i.title for i in sorted(roadmap.items, key=lambda i: i.priority_score, reverse=True)] == [
        "high",
        "mid",
        "low",
    ]


async def test_new_roadmap_supersedes_previous_active_one(db_session):
    repo = await _make_repo(db_session)
    gen = RoadmapGenerator(db_session)

    first = await gen.build(repo.id, None, [_rec("a", 1.0)], "first")
    second = await gen.build(repo.id, None, [_rec("b", 1.0)], "second")

    await db_session.refresh(first)
    assert first.status == RoadmapStatus.SUPERSEDED
    assert second.status == RoadmapStatus.ACTIVE


async def test_empty_recommendations_still_produces_a_roadmap(db_session):
    repo = await _make_repo(db_session)
    roadmap = await RoadmapGenerator(db_session).build(repo.id, None, [], "nothing to do")
    assert roadmap.items == []
    assert roadmap.summary == "nothing to do"
