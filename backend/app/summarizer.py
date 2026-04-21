"""QORA — Post-call summarizer and fact extractor (CAP-4, Phase 2b).

Generates a concise summary and structured facts from a call transcript
using a single GPT-4o-mini call (non-streaming, JSON mode).

Flow:
1. Load transcript turns for the session from DB.
2. If 0 turns → skip (no GPT call, no side-effects).
3. Single GPT-4o-mini call → summary (<=150 tokens) + extracted_facts.
4. Persist summary + facts to CallSession.
5. Merge facts into Lead (objection union, latest values, do_not_call flag).

Failures are always caught and logged — MUST NOT raise, MUST NOT affect
session close or any other operation.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.calls.models import CallSession, TranscriptTurn
from app.leads.models import Lead

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# System prompt for GPT-4o-mini
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a call center analyst. You receive a transcript from an insurance sales call \
and must return a JSON object with exactly these fields:

{
  "summary": "<string, max 150 tokens, plain language summary of the call>",
  "objections": ["<list of objections the lead raised, or empty list>"],
  "interest_level": <integer 0-100, estimated interest level of the lead>,
  "current_insurance": "<current insurance carrier if mentioned, or null>",
  "next_action_suggested": "<one of: call_again, send_quote, wait, do_not_call>",
  "misc_facts": {<any other relevant facts extracted, or empty object>}
}

Rules:
- summary MUST be concise, max 150 tokens
- interest_level: 0 = completely uninterested, 100 = very interested and ready to buy
- next_action_suggested: use do_not_call only if the lead explicitly asked not to be called again
- Always return valid JSON, nothing else
"""


# ---------------------------------------------------------------------------
# Core summarizer function
# ---------------------------------------------------------------------------


async def generate_summary_and_facts(session_id: str, db: AsyncSession) -> None:
    """Generate summary and extract facts from a completed call session.

    Loads transcript turns from DB. If 0 turns, skips without making any
    GPT call. On GPT failure, logs and returns silently — MUST NOT raise.

    Args:
        session_id: UUID of the call session to summarize.
        db: Active async DB session.
    """
    try:
        await _run_summarizer(session_id, db)
    except Exception as exc:
        logger.error(
            "summarizer_unexpected_error",
            session_id=session_id,
            error=str(exc),
            exc_info=True,
        )


async def _run_summarizer(session_id: str, db: AsyncSession) -> None:
    """Internal: runs the full summarize+persist pipeline.

    Separated so the outer function can catch all exceptions in one place.
    """
    # Load transcript turns
    turns_result = await db.execute(
        select(TranscriptTurn)
        .where(TranscriptTurn.session_id == session_id)
        .order_by(TranscriptTurn.timestamp)
    )
    turns = list(turns_result.scalars().all())

    if not turns:
        logger.info(
            "summarizer_skipped_no_turns",
            session_id=session_id,
        )
        return

    # Load the session to get lead_id
    session_result = await db.execute(
        select(CallSession).where(CallSession.id == session_id)
    )
    cs = session_result.scalar_one_or_none()
    if cs is None:
        logger.warning("summarizer_session_not_found", session_id=session_id)
        return

    # Build transcript text for GPT
    transcript_text = _format_transcript(turns)

    # Call GPT-4o-mini
    summary, facts = await _call_gpt_summarize(transcript_text)

    # Persist to CallSession
    user_turns = sum(1 for t in turns if t.role == "user")
    agent_turns = sum(1 for t in turns if t.role == "agent")

    cs.summary = summary
    cs.extracted_facts = facts
    cs.total_user_turns = user_turns
    cs.total_agent_turns = agent_turns

    # Merge into Lead
    if cs.lead_id:
        await _merge_facts_into_lead(db, cs.lead_id, summary, facts)

    await db.flush()

    logger.info(
        "summarizer_complete",
        session_id=session_id,
        turn_count=len(turns),
        user_turns=user_turns,
        agent_turns=agent_turns,
        interest_level=facts.get("interest_level"),
        next_action=facts.get("next_action_suggested"),
    )


def _format_transcript(turns: list[TranscriptTurn]) -> str:
    """Format transcript turns into a readable text block for GPT.

    Args:
        turns: List of TranscriptTurn instances, ordered by timestamp.

    Returns:
        Formatted transcript string.
    """
    lines = []
    for turn in turns:
        role_label = "Agente" if turn.role == "agent" else "Lead"
        lines.append(f"{role_label}: {turn.content}")
    return "\n".join(lines)


async def _call_gpt_summarize(transcript_text: str) -> tuple[str, dict[str, Any]]:
    """Make a single GPT-4o-mini call to summarize and extract facts.

    Uses JSON mode to ensure structured output. On failure, raises
    so the caller (_run_summarizer) can handle it uniformly.

    Args:
        transcript_text: Formatted call transcript.

    Returns:
        Tuple of (summary_text, extracted_facts_dict).

    Raises:
        Exception: On API failure, JSON parse error, or missing fields.
    """
    from app.core.config import Settings

    settings = Settings()
    api_key = settings.openai_api_key.get_secret_value()
    model = settings.openai_model_fast  # gpt-4o-mini

    client = AsyncOpenAI(api_key=api_key)

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Transcript:\n\n{transcript_text}",
            },
        ],
        response_format={"type": "json_object"},
        max_tokens=512,
        temperature=0.2,
    )

    raw_content = response.choices[0].message.content or "{}"

    try:
        data = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        logger.error(
            "summarizer_json_parse_error",
            raw_content=raw_content[:500],
            error=str(exc),
        )
        raise

    summary = str(data.get("summary", ""))

    facts: dict[str, Any] = {
        "objections": data.get("objections", []),
        "interest_level": data.get("interest_level", 50),
        "current_insurance": data.get("current_insurance"),
        "next_action_suggested": data.get("next_action_suggested", "wait"),
        "misc_facts": data.get("misc_facts", {}),
    }

    return summary, facts


# ---------------------------------------------------------------------------
# Lead merge logic
# ---------------------------------------------------------------------------


async def _merge_facts_into_lead(
    db: AsyncSession,
    lead_id: str,
    summary: str,
    facts: dict[str, Any],
) -> None:
    """Merge extracted facts into the Lead record.

    - summary_last_call ← current summary
    - objections_heard ← union of existing + new (deduplicated)
    - interest_level ← latest value
    - extracted_facts ← merge: new non-null fields overwrite old
    - do_not_call ← True if next_action_suggested == "do_not_call"

    Args:
        db: Active async DB session.
        lead_id: UUID of the lead to update.
        summary: Call summary text.
        facts: Extracted facts dict from GPT.
    """
    lead_result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = lead_result.scalar_one_or_none()
    if lead is None:
        logger.warning("summarizer_lead_not_found", lead_id=lead_id)
        return

    # summary_last_call ← current summary
    lead.summary_last_call = summary

    # objections_heard ← union (not replace)
    existing_objections: list[str] = []
    if lead.objections_heard:
        if isinstance(lead.objections_heard, str):
            try:
                existing_objections = json.loads(lead.objections_heard)
            except (json.JSONDecodeError, TypeError):
                existing_objections = []
        elif isinstance(lead.objections_heard, list):
            existing_objections = list(lead.objections_heard)

    new_objections = facts.get("objections") or []
    merged_objections = list(set(existing_objections + new_objections))
    lead.objections_heard = merged_objections

    # interest_level ← latest
    if facts.get("interest_level") is not None:
        lead.interest_level = int(facts["interest_level"])

    # extracted_facts ← merge: new non-null fields overwrite old
    existing_facts: dict[str, Any] = {}
    if lead.extracted_facts:
        if isinstance(lead.extracted_facts, str):
            try:
                existing_facts = json.loads(lead.extracted_facts)
            except (json.JSONDecodeError, TypeError):
                existing_facts = {}
        elif isinstance(lead.extracted_facts, dict):
            existing_facts = dict(lead.extracted_facts)

    new_facts_clean = {k: v for k, v in facts.items() if v is not None}
    lead.extracted_facts = {**existing_facts, **new_facts_clean}

    # do_not_call ← True if suggested
    if facts.get("next_action_suggested") == "do_not_call":
        lead.do_not_call = True

    # next_action ← latest suggested action
    if facts.get("next_action_suggested"):
        lead.next_action = facts["next_action_suggested"]
