"""Turns a ProjectRealityModel snapshot + TechnologyIntel rows + pattern
findings into a list of recommendations. Deterministic and rule-based by
design — no LLM call is required to produce a recommendation, and none of
the priority math below depends on one. This is a deliberate choice: an
LLM asked to "recommend improvements" from a repo summary will produce
plausible-sounding, unverifiable claims (the exact failure mode that
produced the NEIS draft this module replaces — see the README's
"Post-release audit fixes" section). Every recommendation this engine
produces traces back to a specific measured fact.

The only optional LLM involvement is a one-paragraph narrative summary for
the roadmap as a whole (see summarize()) — additive, best-effort, and the
roadmap is fully usable without it.
"""

from models.neis.evolution_roadmap import EffortEstimate, RecommendationCategory
from models.neis.project_reality import ProjectRealityModel
from models.neis.technology_intel import TechnologyIntel
from models.neis.user_intent import UserIntent
from providers.base import AIProvider

DEFAULT_WEIGHT = 1.0
LOW_HEALTH_THRESHOLD = 60.0
LOW_TEST_RATIO_THRESHOLD = 0.15


class InnovationReasoningEngine:
    def generate_recommendations(
        self,
        reality: ProjectRealityModel,
        tech_intel: list[TechnologyIntel],
        patterns: list[dict],
        intent: UserIntent | None,
    ) -> list[dict]:
        weights = (intent.priority_weights if intent else {}) or {}
        constraints = [c.lower() for c in (intent.constraints if intent else []) or []]

        recommendations: list[dict] = []
        recommendations.extend(self._dependency_recommendations(tech_intel, weights))
        recommendations.extend(self._pattern_recommendations(patterns, weights))
        recommendations.extend(self._health_recommendations(reality, weights))

        return [r for r in recommendations if not self._suppressed_by_constraint(r, constraints)]

    def _dependency_recommendations(self, tech_intel: list[TechnologyIntel], weights: dict) -> list[dict]:
        recs = []
        for t in tech_intel:
            if not t.is_outdated or not t.major_versions_behind:
                continue
            base_score = min(t.major_versions_behind * 2.0, 10.0)
            recs.append(
                {
                    "category": RecommendationCategory.DEPENDENCY,
                    "title": f"Upgrade {t.package_name} ({t.current_version} → {t.latest_version})",
                    "rationale": f"{t.package_name} is {t.major_versions_behind} major version(s) behind the "
                    f"latest release on {t.ecosystem.value}. Major-version gaps compound: each additional "
                    f"release behind makes the eventual upgrade riskier and more likely to require broader "
                    f"changes than the last one would have.",
                    "priority_score": base_score * weights.get("dependency", DEFAULT_WEIGHT),
                    "effort_estimate": EffortEstimate.SMALL if t.major_versions_behind == 1 else EffortEstimate.MEDIUM,
                }
            )
        return recs

    def _pattern_recommendations(self, patterns: list[dict], weights: dict) -> list[dict]:
        recs = []
        for p in patterns:
            if p["pattern_type"] == "god_class":
                recs.append(
                    {
                        "category": RecommendationCategory.ARCHITECTURE,
                        "title": f"Split {p['subject']}",
                        "rationale": p["summary"],
                        "priority_score": min(p["method_count"] / 5.0, 10.0)
                        * weights.get("architecture", DEFAULT_WEIGHT),
                        "effort_estimate": EffortEstimate.LARGE,
                    }
                )
            elif p["pattern_type"] == "high_coupling_file":
                recs.append(
                    {
                        "category": RecommendationCategory.ARCHITECTURE,
                        "title": f"Reduce coupling on {p['subject']}",
                        "rationale": p["summary"],
                        "priority_score": min(p["fan_in"] / 2.0, 10.0) * weights.get("architecture", DEFAULT_WEIGHT),
                        "effort_estimate": EffortEstimate.MEDIUM,
                    }
                )
        return recs

    def _health_recommendations(self, reality: ProjectRealityModel, weights: dict) -> list[dict]:
        recs = []
        components = reality.health_components or {}

        if reality.health_score is not None and reality.health_score < LOW_HEALTH_THRESHOLD:
            test_ratio = components.get("test_to_code_file_ratio")
            if test_ratio is not None and test_ratio < LOW_TEST_RATIO_THRESHOLD:
                recs.append(
                    {
                        "category": RecommendationCategory.TESTING,
                        "title": "Increase test coverage",
                        "rationale": f"Test-to-code file ratio is {test_ratio:.2f}, well below a "
                        f"{LOW_TEST_RATIO_THRESHOLD:.2f} baseline, and overall health score is "
                        f"{reality.health_score:.1f}/100.",
                        "priority_score": 7.0 * weights.get("testing", DEFAULT_WEIGHT),
                        "effort_estimate": EffortEstimate.LARGE,
                    }
                )
            docstring_coverage = components.get("docstring_coverage")
            if docstring_coverage is not None and docstring_coverage < 0.3:
                recs.append(
                    {
                        "category": RecommendationCategory.DOCUMENTATION,
                        "title": "Improve docstring coverage",
                        "rationale": f"Docstring coverage is {docstring_coverage:.0%}, making the codebase "
                        f"harder to navigate without reading full implementations.",
                        "priority_score": 3.0 * weights.get("documentation", DEFAULT_WEIGHT),
                        "effort_estimate": EffortEstimate.MEDIUM,
                    }
                )
        return recs

    def _suppressed_by_constraint(self, recommendation: dict, constraints: list[str]) -> bool:
        """Substring match against title+rationale — a heuristic, not NLP.
        Documented as such in models/neis/user_intent.py; false negatives
        (a constraint that doesn't happen to share wording with a
        recommendation) are expected and acceptable, since the alternative
        is either no suppression at all or an LLM call per recommendation."""
        haystack = f"{recommendation['title']} {recommendation['rationale']}".lower()
        return any(c in haystack for c in constraints if c)

    async def summarize(self, recommendations: list[dict], provider: AIProvider | None) -> str:
        """Best-effort one-paragraph narrative. Never the source of a
        recommendation, never required — falls back to a deterministic
        template if no provider is configured or the call fails for any
        reason (network, auth, rate limit, malformed response)."""
        fallback = self._deterministic_summary(recommendations)
        if not provider or not recommendations:
            return fallback
        try:
            listing = "\n".join(f"- [{r['category'].value}] {r['title']}" for r in recommendations[:10])
            response = await provider.explain(
                code=listing,
                context={"task": "Summarize this repository evolution roadmap in one short paragraph."},
            )
            return response.content.strip() or fallback
        except Exception:
            return fallback

    def _deterministic_summary(self, recommendations: list[dict]) -> str:
        if not recommendations:
            return "No recommendations generated — either the repository is in good shape by the metrics NEIS checks, or the underlying analysis (project model, tech scout, or pattern extraction) didn't produce enough signal."
        by_category: dict[str, int] = {}
        for r in recommendations:
            key = r["category"].value
            by_category[key] = by_category.get(key, 0) + 1
        parts = ", ".join(f"{count} {cat}" for cat, count in sorted(by_category.items()))
        return f"{len(recommendations)} recommendation(s) generated: {parts}. See roadmap items for details."
