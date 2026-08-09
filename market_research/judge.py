"""Judge Agent. Sits between ResearchScout and OpportunityEngine and is the
answer to "what should we build's" actual failure mode: raw search results
are noisy (marketing copy, outdated posts, off-topic hits, SEO spam) and
handing all of it to a provider asked to "propose opportunities" is how you
get plausible-sounding nonsense — the same problem innovation_engine.py's
docstring describes and was rewritten to avoid.

Fail-closed by design: if no AI provider is configured, or a judgment call
fails or doesn't parse, the signal is REJECTED, not ACCEPTED. An
under-filtered research pipeline is a nuisance (fewer opportunities surface);
an unfiltered one feeds noise straight into a provider that then proposes
features off it. Silence should never read as approval here.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.neis.external_opportunity import ExternalSignal, JudgeVerdict
from providers.base import AIProvider

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


JUDGE_PROMPT_TEMPLATE = """You are screening one external research finding for a software \
engineering roadmap tool. Decide only whether this finding is (a) genuinely relevant to the \
stated repository context and (b) from a source specific and credible enough to act on — not \
whether it's a good idea.

Repository context: {repo_context}

Finding:
Title: {title}
URL: {url}
Snippet: {snippet}

Respond in exactly this format, nothing else:
VERDICT: accepted or rejected
RATIONALE: one sentence explaining why"""


class JudgeAgent:
    def __init__(self, session: AsyncSession, provider: AIProvider | None):
        self.session = session
        self.provider = provider

    async def judge_pending(self, repository_id: int, repo_context: str) -> list[ExternalSignal]:
        """Judges every PENDING signal for this repository. Returns the
        full set of judged signals (both verdicts) — callers that only
        want ACCEPTED ones should filter the result themselves, so the
        return value stays an honest record of what was judged, not a
        pre-filtered convenience view.
        """
        stmt = select(ExternalSignal).where(
            ExternalSignal.repository_id == repository_id,
            ExternalSignal.judge_verdict == JudgeVerdict.PENDING,
        )
        pending = (await self.session.execute(stmt)).scalars().all()

        judged = []
        for signal in pending:
            await self._judge_one(signal, repo_context)
            judged.append(signal)
        await self.session.flush()
        return judged

    async def _judge_one(self, signal: ExternalSignal, repo_context: str) -> None:
        if not self.provider:
            signal.judge_verdict = JudgeVerdict.REJECTED
            signal.judge_rationale = "No AI provider configured — rejected by default (fail-closed)."
            signal.judged_at = _utcnow()
            return

        try:
            response = await self.provider.analyze(
                code=signal.snippet,
                context={
                    "task": JUDGE_PROMPT_TEMPLATE.format(
                        repo_context=repo_context, title=signal.title, url=signal.url, snippet=signal.snippet
                    )
                },
            )
            verdict, rationale = self._parse(response.content)
        except Exception as e:
            logger.warning(f"market_research.judge: signal {signal.id} judgment failed — {e}")
            verdict, rationale = JudgeVerdict.REJECTED, f"Judgment call failed — rejected by default ({e})."

        signal.judge_verdict = verdict
        signal.judge_rationale = rationale
        signal.judged_at = _utcnow()

    def _parse(self, content: str) -> tuple[JudgeVerdict, str]:
        verdict = JudgeVerdict.REJECTED
        rationale = "Provider response did not follow the expected VERDICT/RATIONALE format — rejected by default."

        lines = [line.strip() for line in content.strip().splitlines() if line.strip()]
        verdict_line = next((line for line in lines if line.upper().startswith("VERDICT:")), None)
        rationale_line = next((line for line in lines if line.upper().startswith("RATIONALE:")), None)

        if verdict_line:
            value = verdict_line.split(":", 1)[1].strip().lower()
            if value == "accepted":
                verdict = JudgeVerdict.ACCEPTED
            elif value == "rejected":
                verdict = JudgeVerdict.REJECTED
            else:
                return JudgeVerdict.REJECTED, rationale  # unrecognized value — fail closed, keep default message

        if rationale_line:
            rationale = rationale_line.split(":", 1)[1].strip() or rationale

        return verdict, rationale
