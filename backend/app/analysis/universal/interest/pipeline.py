"""Interest pipeline orchestrator — Phase 1 (Agent 1) then Phase 2 (Agent 2).

Contract
--------
``run_interest_pipeline`` calls Agent 1 (interests) first.  If Agent 1
succeeds, Agent 2 (interest_level) runs with its output.  Failures produce
distinguishable error dicts (with an ``"error"`` key) rather than silent
defaults so that monitoring queries can differentiate:

    * Normal empty result:  ``InterestsAxis(items=[])``   — no ``"error"`` key
    * Agent 1 failure:      ``{"error": "...", "failed_agent": "interests"}``

Error propagation:
    Agent 1 fails → BOTH results are error dicts; Agent 2 does NOT run
    Agent 2 fails → Agent 1 result is preserved; level_result is error dict
"""

from __future__ import annotations

import logging

from openai import AsyncOpenAI

from app.analysis.universal.interest.interest_level import (
    InterestLevelResult,
    analyze as interest_level_analyze,
)
from app.analysis.universal.interest.interests import (
    InterestsAxis,
    analyze as interests_analyze,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Error marker helpers
# ---------------------------------------------------------------------------


def _interests_error_marker(exc: Exception) -> dict:
    """Return a detectable error dict for the interests field."""
    return {
        "error": str(exc),
        "failed_agent": "interests",
    }


def _interest_level_error_marker(exc: Exception) -> dict:
    """Return a detectable error dict for the interest_level field."""
    return {
        "error": str(exc),
        "failed_agent": "interest_level",
    }


def _interest_level_skipped_marker() -> dict:
    """Return a detectable error dict when Agent 2 is skipped due to Agent 1 failure."""
    return {
        "error": "skipped — Agent 1 (interests) failed",
        "failed_agent": "interest_level",
    }


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


async def run_interest_pipeline(
    transcript: str,
    client: AsyncOpenAI,
    *,
    previous_score: int | None = None,
    language: str = "Spanish",
) -> tuple[InterestsAxis | dict, InterestLevelResult | dict]:
    """Run the 2-phase interest pipeline.

    Phase 1: Agent 1 (interests.analyze) — detect product interests
    Phase 2: Agent 2 (interest_level.analyze) — score detected interests

    Args:
        transcript: Formatted transcript text.
        client: AsyncOpenAI client instance.
        previous_score: Lead's prior interest score for 70/30 formula.
        language: Output language for human-readable text fields (evidence,
            reason, signals). Canonical codes (product IDs, level, confidence)
            stay in English.

    Returns:
        ``(interests_result, level_result)`` where either element can be
        an error dict (has ``"error"`` key) if the corresponding agent failed.
    """
    # ------------------------------------------------------------------
    # Phase 1 — Agent 1
    # ------------------------------------------------------------------
    try:
        interests_result: InterestsAxis | dict = await interests_analyze(
            transcript, client, language=language
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("interest_pipeline_agent1_failed: %s", exc, exc_info=True)
        return _interests_error_marker(exc), _interest_level_skipped_marker()

    # ------------------------------------------------------------------
    # Phase 2 — Agent 2 (only if Phase 1 succeeded)
    # ------------------------------------------------------------------
    try:
        level_result: InterestLevelResult | dict = await interest_level_analyze(
            transcript,
            client,
            interests=interests_result,
            previous_score=previous_score,
            language=language,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("interest_pipeline_agent2_failed: %s", exc, exc_info=True)
        return interests_result, _interest_level_error_marker(exc)

    return interests_result, level_result
