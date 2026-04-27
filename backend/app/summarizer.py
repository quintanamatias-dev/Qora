"""QORA — Post-call summarizer and fact extractor (CAP-4, Phase 5).

Generates a concise summary and structured facts from a call transcript
using a single GPT-4o-mini call with OpenAI Structured Outputs (parse mode).

Phase 5 changes:
- Switched from `create()` + JSON mode to `parse(response_format=PostCallAnalysis)`
- Imports PostCallAnalysis + ANALYSIS_SYSTEM_PROMPT from analysis_schema (N8N boundary)
- max_tokens increased to 1024 (3 new nested axes need more tokens)
- _SYSTEM_PROMPT removed — now lives in analysis_schema.ANALYSIS_SYSTEM_PROMPT
- _call_gpt_summarize updated to use .parse() and return typed Pydantic result
- _merge_facts_into_lead preserves all existing merge logic + new axes flow naturally

Flow:
1. Load transcript turns for the session from DB.
2. If 0 turns → skip (no GPT call, no side-effects).
3. Single GPT-4o-mini call → PostCallAnalysis Pydantic object.
4. model_dump() → facts dict (summary popped out).
5. Persist summary + facts to CallSession.
6. Merge facts into Lead (objection union, latest values, do_not_call flag).

Failures are always caught and logged — MUST NOT raise, MUST NOT affect
session close or any other operation.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis_schema import (
    ANALYSIS_SYSTEM_PROMPT,
    ExtractionConfig,
    PostCallAnalysis,
    build_analysis_model,
    build_system_prompt,
)
from app.calls.models import CallAnalysis, CallSession, TranscriptTurn
from app.leads.models import Lead, LeadInterestHistory, LeadProfileFact

logger = structlog.get_logger(__name__)


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

    Atomicity guarantee (Issue #34 CRITICAL 1):
    All writes — both legacy fields (CallSession.summary/extracted_facts) and
    new-table writes (CallAnalysis, LeadProfileFact, LeadInterestHistory) — are
    wrapped in a savepoint (nested transaction).  If ANY write fails, the savepoint
    rolls back and NO partial data is committed.
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

    # Load client's extraction config (Issue #35)
    extraction_cfg = await _load_extraction_config(db, cs.client_id)

    # Call GPT-4o-mini with structured outputs
    # On failure, persist a partial-analysis marker so the record shows
    # that analysis was attempted but failed (spec requirement: CRITICAL 1).
    user_turns = sum(1 for t in turns if t.role == "user")
    agent_turns = sum(1 for t in turns if t.role == "agent")

    try:
        summary, facts = await _call_gpt_summarize(
            transcript_text, config=extraction_cfg
        )
    except Exception as gpt_exc:
        error_msg = str(gpt_exc)
        logger.warning(
            "summarizer_analysis_failed_partial_marker",
            session_id=session_id,
            error=error_msg,
        )
        async with db.begin_nested():
            cs.total_user_turns = user_turns
            cs.total_agent_turns = agent_turns
            cs.extracted_facts = {
                "_analysis_status": "failed",
                "_analysis_error": error_msg,
            }
            # ★ NEW: Write CallAnalysis failure marker (analysis v2 — same savepoint)
            await _upsert_call_analysis_failed(
                db, cs.id, cs.lead_id, cs.client_id, error_msg
            )
        return

    # ★ Wrap ALL persistence in a single savepoint — guarantees atomicity.
    # If _upsert_call_analysis or any other write raises, the savepoint rolls back
    # and legacy fields (summary, extracted_facts) are NOT committed.
    async with db.begin_nested():
        # Persist to CallSession (legacy path)
        cs.summary = summary
        cs.extracted_facts = facts
        cs.total_user_turns = user_turns
        cs.total_agent_turns = agent_turns

        # ★ NEW: Dual-write to CallAnalysis (analysis v2 — same savepoint, atomic)
        await _upsert_call_analysis(db, cs.id, cs.lead_id, cs.client_id, summary, facts)

        # Merge into Lead
        if cs.lead_id:
            await _merge_facts_into_lead(
                db, cs.lead_id, summary, facts, session_id=cs.id
            )

        # Auto-schedule follow-up call if eligible (Phase 6)
        if cs.lead_id and cs.client_id:
            await _auto_schedule_if_needed(db, cs, facts)

    logger.info(
        "summarizer_complete",
        session_id=session_id,
        turn_count=len(turns),
        user_turns=user_turns,
        agent_turns=agent_turns,
        interest_level=facts.get("interest_level"),
        next_action=facts.get("next_action_suggested"),
        call_outcome=facts.get("call_outcome", {}).get("classification"),
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


def _get_openai_client() -> tuple[AsyncOpenAI, str]:
    """Build an OpenAI client from application settings.

    Extracted as a separate function so tests can patch it easily.
    Returns (client, model_name).
    """
    from app.core.config import Settings

    settings = Settings()
    api_key = settings.openai_api_key.get_secret_value()
    model = settings.openai_model_fast  # gpt-4o-mini
    client = AsyncOpenAI(api_key=api_key)
    return client, model


async def _call_gpt_summarize(
    transcript_text: str,
    *,
    config: "ExtractionConfig | None" = None,
) -> tuple[str, dict[str, Any]]:
    """Make a single GPT-4o-mini call using Structured Outputs (parse mode).

    When config is provided, uses build_analysis_model(config) as response_format
    and build_system_prompt(config) as the system message.
    When config is None, falls back to PostCallAnalysis + ANALYSIS_SYSTEM_PROMPT.

    Args:
        transcript_text: Formatted call transcript.
        config: Optional ExtractionConfig for dynamic model/prompt selection.

    Returns:
        Tuple of (summary_text, extracted_facts_dict).

    Raises:
        Exception: On API failure, schema parse error, or refusal.
    """
    client, model = _get_openai_client()

    # Issue #35: select response_format and system prompt based on config
    if config is not None:
        response_format = build_analysis_model(config)
        system_prompt = build_system_prompt(config)
    else:
        response_format = PostCallAnalysis
        system_prompt = ANALYSIS_SYSTEM_PROMPT

    response = await client.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"Transcript:\n\n{transcript_text}",
            },
        ],
        response_format=response_format,
        max_tokens=1024,
        temperature=0.2,
    )

    message = response.choices[0].message

    # Handle refusal (OpenAI can refuse to analyze certain content)
    if message.refusal:
        logger.warning(
            "summarizer_llm_refusal",
            refusal=message.refusal[:200],
        )
        raise ValueError(f"LLM refused to analyze transcript: {message.refusal[:100]}")

    if message.parsed is None:
        logger.error("summarizer_parse_returned_none")
        raise ValueError("OpenAI parse() returned None — unexpected empty response")

    analysis: PostCallAnalysis = message.parsed

    # model_dump() gives us the full structured facts dict
    facts = analysis.model_dump()

    # Pop summary out — it's stored separately on CallSession
    summary = str(facts.pop("summary", ""))

    return summary, facts


# ---------------------------------------------------------------------------
# Lead merge logic
# ---------------------------------------------------------------------------


async def _merge_facts_into_lead(
    db: AsyncSession,
    lead_id: str,
    summary: str,
    facts: dict[str, Any],
    *,
    session_id: str | None = None,
) -> None:
    """Merge extracted facts into the Lead record and dual-write to new relational tables.

    Legacy JSON path (unchanged):
    - summary_last_call ← current summary
    - objections_heard ← union of existing + new (deduplicated)
    - interest_level ← latest value
    - extracted_facts ← merge: new non-null fields overwrite old
    - do_not_call ← True if next_action_suggested == "do_not_call"
    - call_outcome, detected_interests, identified_problem ← overwrite (latest wins)

    ★ NEW (analysis v2 dual-write):
    - LeadProfileFact rows for key scalar facts (upsert semantics via superseded_at)
    - LeadInterestHistory row for interest_level (append-only)

    Args:
        db: Active async DB session.
        lead_id: UUID of the lead to update.
        summary: Call summary text.
        facts: Extracted facts dict from GPT (already model_dump()'d).
        session_id: Optional UUID of the source call session (for FK reference).
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
    # Analysis axes (call_outcome, detected_interests, identified_problem) use
    # overwrite strategy (latest call wins — per spec).
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

    # data_corrections ← propagate car_make/car_model/car_year to Lead columns (Issue #21)
    corrections_str = facts.get("data_corrections") or ""
    if corrections_str:
        _apply_data_corrections(lead, corrections_str)

    # ★ NEW: Dual-write to relational tables (analysis v2)
    await _write_lead_profile_facts(db, lead_id, session_id, facts)
    _write_interest_history(db, lead_id, session_id, facts)

    # ★ NEW: Write LeadProfileFact rows for each data_correction (Issue #34 CRITICAL 2)
    if corrections_str:
        await _write_correction_facts(db, lead_id, session_id, corrections_str)


# ---------------------------------------------------------------------------
# Correction propagation helper (Issue #21)
# ---------------------------------------------------------------------------


async def _auto_schedule_if_needed(
    db: AsyncSession,
    cs: "CallSession",
    facts: dict[str, Any],
) -> None:
    """Call scheduler_service.auto_schedule() after lead merge.

    Graceful: any exception is caught and logged. MUST NOT re-raise.
    Lead facts are already persisted when this is called.

    Args:
        db: Active async DB session.
        cs: The completed CallSession.
        facts: Extracted facts from post-call analysis.
    """
    try:
        from app.scheduler.service import auto_schedule

        await auto_schedule(
            db=db,
            session_id=cs.id,
            lead_id=cs.lead_id,
            client_id=cs.client_id,
            facts=facts,
            agent_id=getattr(cs, "agent_id", None),
        )
    except Exception as exc:
        logger.warning(
            "auto_schedule_failed",
            session_id=cs.id,
            lead_id=cs.lead_id,
            error=str(exc),
        )


def _apply_data_corrections(lead: "Lead", corrections_str: str) -> None:
    """Parse 'field: value' lines from data_corrections and update Lead columns.

    Supported fields: car_make, car_model, car_year.
    Ignores unrecognized fields (forward-compatible).
    car_year is parsed as int; others as stripped strings.

    Args:
        lead: Lead ORM instance to update.
        corrections_str: Free-text string with 'field: value' per line.
    """
    if not corrections_str or not corrections_str.strip():
        return

    _SUPPORTED_FIELDS = {"car_make", "car_model", "car_year"}

    for line in corrections_str.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        # Split on first colon only
        field, _, value = line.partition(":")
        field = field.strip()
        value = value.strip()

        if field not in _SUPPORTED_FIELDS:
            continue

        if field == "car_year":
            try:
                setattr(lead, field, int(value))
            except (ValueError, TypeError):
                pass  # ignore malformed year — forward-compatible
        else:
            if value:
                setattr(lead, field, value)


# ---------------------------------------------------------------------------
# Analysis v2 helpers — dual-write to relational tables
# ---------------------------------------------------------------------------


def _new_uuid() -> str:
    """Generate a new UUID4 string (matches project PK convention)."""
    return str(uuid.uuid4())


async def _load_extraction_config(
    db: AsyncSession,
    client_id: str,
) -> "ExtractionConfig | None":
    """Load and deserialize Client.extraction_config for the given client.

    Returns ExtractionConfig if the client has a non-NULL extraction_config,
    or None (base path / backward compat) if extraction_config is NULL or missing.

    Args:
        db: Active async DB session.
        client_id: The client whose extraction config to load.

    Returns:
        ExtractionConfig instance or None.
    """
    from app.tenants.models import Client

    result = await db.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if client is None or client.extraction_config is None:
        return None

    try:
        config_dict = json.loads(client.extraction_config)
        return ExtractionConfig.model_validate(config_dict)
    except Exception as exc:
        logger.warning(
            "summarizer_invalid_extraction_config",
            client_id=client_id,
            error=str(exc),
        )
        return None


async def _upsert_call_analysis(
    db: AsyncSession,
    session_id: str,
    lead_id: str | None,
    client_id: str,
    summary: str,
    facts: dict[str, Any],
) -> None:
    """Insert or update a CallAnalysis row for the given session_id.

    On re-run (e.g. webhook retry), updates the existing row in-place.
    On first run, inserts a new row with a fresh UUID.

    Args:
        db: Active async DB session.
        session_id: UUID of the source call session.
        lead_id: Optional UUID of the lead.
        client_id: UUID of the client.
        summary: Call summary text.
        facts: Extracted facts dict (model_dump()'d PostCallAnalysis).
    """
    call_outcome = facts.get("call_outcome") or {}
    detected_interests = facts.get("detected_interests") or {}
    identified_problem = facts.get("identified_problem") or {}

    # Check for existing row
    existing_result = await db.execute(
        select(CallAnalysis).where(CallAnalysis.session_id == session_id)
    )
    ca = existing_result.scalar_one_or_none()

    if ca is None:
        ca = CallAnalysis(id=_new_uuid(), session_id=session_id)
        db.add(ca)

    # Set or update all fields
    ca.lead_id = lead_id
    ca.client_id = client_id
    ca.summary = summary
    ca.interest_level = facts.get("interest_level")
    ca.classification = _str_or_none(call_outcome.get("classification"))
    ca.engagement_quality = _str_or_none(call_outcome.get("engagement_quality"))
    ca.outcome_reason = call_outcome.get("reason")
    ca.urgency = _str_or_none(identified_problem.get("urgency"))
    ca.primary_need = identified_problem.get("primary_need")
    ca.next_action_suggested = facts.get("next_action_suggested")
    ca.current_insurance = facts.get("current_insurance")
    ca.data_corrections = facts.get("data_corrections") or ""
    ca.misc_notes = facts.get("misc_notes") or ""
    ca.objections = _to_json_list(facts.get("objections"))
    ca.products = _to_json_list(detected_interests.get("products"))
    ca.specific_needs = _to_json_list(detected_interests.get("specific_needs"))
    ca.buying_signals = _to_json_list(detected_interests.get("buying_signals"))
    ca.pain_points = _to_json_list(identified_problem.get("pain_points"))
    # Issue #35 — 4 new universal axes
    ca.service_issues = _to_json_list((facts.get("service_issues") or {}).get("issues"))
    ca.profile_facts = _to_json_list((facts.get("profile_facts") or {}).get("facts"))
    ca.commitment_signals = _to_json_list(
        (facts.get("commitment_signals") or {}).get("signals")
    )
    _abandonment = facts.get("abandonment_reason") or {}
    ca.abandonment_reason = _abandonment.get("reason")
    ca.extra_axes_data = (
        json.dumps(facts.get("extra_axes_data"))
        if facts.get("extra_axes_data") is not None
        else None
    )
    ca.analysis_status = "ok"
    ca.analysis_error = None


async def _upsert_call_analysis_failed(
    db: AsyncSession,
    session_id: str,
    lead_id: str | None,
    client_id: str,
    error_msg: str,
) -> None:
    """Insert or update a CallAnalysis failure marker row.

    Args:
        db: Active async DB session.
        session_id: UUID of the source call session.
        lead_id: Optional UUID of the lead.
        client_id: UUID of the client.
        error_msg: Error message from the failed GPT call.
    """
    existing_result = await db.execute(
        select(CallAnalysis).where(CallAnalysis.session_id == session_id)
    )
    ca = existing_result.scalar_one_or_none()

    if ca is None:
        ca = CallAnalysis(id=_new_uuid(), session_id=session_id)
        db.add(ca)

    ca.lead_id = lead_id
    ca.client_id = client_id
    ca.analysis_status = "failed"
    ca.analysis_error = error_msg


def _str_or_none(value: Any) -> str | None:
    """Return string representation of value, or None if value is None.

    Handles enum values by extracting .value (Pydantic model_dump() may return
    enum objects when mode='python' is used — the default).
    """
    if value is None:
        return None
    # Handle enum values (e.g. OutcomeClassification.interested → 'interested')
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _to_json_list(value: Any) -> str:
    """Serialize value to a JSON list string. Returns '[]' if None or not a list."""
    if isinstance(value, list):
        return json.dumps(value)
    return "[]"


async def _write_lead_profile_facts(
    db: AsyncSession,
    lead_id: str,
    session_id: str | None,
    facts: dict[str, Any],
) -> None:
    """Write LeadProfileFact rows for key scalar facts from this call.

    Upsert semantics: for singular facts (interest_level, current_insurance,
    next_action, primary_need, classification), supersede any existing active row
    (superseded_at IS NULL) when the value changes.

    Append-only facts (do_not_call) are inserted unconditionally.

    Args:
        db: Active async DB session.
        lead_id: UUID of the lead to write facts for.
        session_id: UUID of the source call session (for FK + provenance).
        facts: Extracted facts dict from GPT.
    """
    from datetime import datetime, timezone

    call_outcome = facts.get("call_outcome") or {}
    identified_problem = facts.get("identified_problem") or {}

    # Build map of fact_key → fact_value for singular facts
    singular_facts: dict[str, str] = {}

    il = facts.get("interest_level")
    if il is not None:
        singular_facts["interest_level"] = str(il)

    ci = facts.get("current_insurance")
    if ci is not None:
        singular_facts["current_insurance"] = str(ci)

    na = facts.get("next_action_suggested")
    if na is not None:
        singular_facts["next_action"] = str(na)

    pn = identified_problem.get("primary_need")
    if pn is not None:
        singular_facts["primary_need"] = str(pn)

    clf = call_outcome.get("classification")
    if clf is not None:
        singular_facts["classification"] = _str_or_none(clf) or str(clf)

    # do_not_call is a special append-only fact
    if facts.get("next_action_suggested") == "do_not_call":
        singular_facts["do_not_call"] = "true"

    now = datetime.now(timezone.utc)

    for fact_key, fact_value in singular_facts.items():
        # Supersede existing active row if value is different
        existing_result = await db.execute(
            select(LeadProfileFact).where(
                LeadProfileFact.lead_id == lead_id,
                LeadProfileFact.fact_key == fact_key,
                LeadProfileFact.superseded_at == None,  # noqa: E711
            )
        )
        existing = existing_result.scalar_one_or_none()

        if existing is not None:
            if existing.fact_value == fact_value:
                # Same value — skip (no change)
                continue
            # Different value — supersede old
            existing.superseded_at = now

        # Insert new active row
        db.add(
            LeadProfileFact(
                id=_new_uuid(),
                lead_id=lead_id,
                fact_key=fact_key,
                fact_value=fact_value,
                source_call_id=session_id,
            )
        )

    # ★ NEW (Issue #36): Append-only list-type facts with namespace prefixes
    # Axes: profile_facts.facts, pain_points, service_issues.issues,
    #       commitment_signals.signals, detected_interests.buying_signals
    # Dedup: normalized (strip().lower()) fact_key match against active rows
    _LIST_AXES: list[tuple[str, list[str]]] = [
        ("profile:", (facts.get("profile_facts") or {}).get("facts") or []),
        ("pain:", (facts.get("identified_problem") or {}).get("pain_points") or []),
        ("service_issue:", (facts.get("service_issues") or {}).get("issues") or []),
        ("signal:", (facts.get("commitment_signals") or {}).get("signals") or []),
        (
            "buying_signal:",
            (facts.get("detected_interests") or {}).get("buying_signals") or [],
        ),
    ]

    for namespace_prefix, items in _LIST_AXES:
        if not items:
            continue
        for raw_item in items:
            if not raw_item or not str(raw_item).strip():
                continue
            normalized = str(raw_item).strip().lower()
            namespaced_key = f"{namespace_prefix}{normalized}"

            # Skip if an active row with this exact (normalized) fact_key already exists
            existing_result = await db.execute(
                select(LeadProfileFact).where(
                    LeadProfileFact.lead_id == lead_id,
                    LeadProfileFact.fact_key == namespaced_key,
                    LeadProfileFact.superseded_at == None,  # noqa: E711
                )
            )
            if existing_result.scalar_one_or_none() is not None:
                continue  # Deduplication: skip existing active row

            # Insert new append-only row
            db.add(
                LeadProfileFact(
                    id=_new_uuid(),
                    lead_id=lead_id,
                    fact_key=namespaced_key,
                    fact_value=normalized,
                    source_call_id=session_id,
                )
            )


async def _write_correction_facts(
    db: AsyncSession,
    lead_id: str,
    session_id: str | None,
    corrections_str: str,
) -> None:
    """Write LeadProfileFact rows for each parsed data_correction field.

    Upsert semantics: supersedes any existing active row for the same fact_key
    when the value changes.  Confidence is implicitly 'high' (explicit correction from GPT).

    Supported fields: car_make, car_model, car_year (same set as _apply_data_corrections).

    Args:
        db: Active async DB session.
        lead_id: UUID of the lead.
        session_id: UUID of the source call session (FK + provenance).
        corrections_str: Free-text string with 'field: value' per line.
    """
    from datetime import datetime, timezone

    if not corrections_str or not corrections_str.strip():
        return

    _SUPPORTED_FIELDS = {"car_make", "car_model", "car_year"}
    now = datetime.now(timezone.utc)

    for line in corrections_str.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field = field.strip()
        value = value.strip()

        if field not in _SUPPORTED_FIELDS or not value:
            continue

        # Supersede existing active row if value differs
        existing_result = await db.execute(
            select(LeadProfileFact).where(
                LeadProfileFact.lead_id == lead_id,
                LeadProfileFact.fact_key == field,
                LeadProfileFact.superseded_at == None,  # noqa: E711
            )
        )
        existing = existing_result.scalar_one_or_none()

        if existing is not None:
            if existing.fact_value == value:
                continue  # Same value — skip
            existing.superseded_at = now

        db.add(
            LeadProfileFact(
                id=_new_uuid(),
                lead_id=lead_id,
                fact_key=field,
                fact_value=value,
                source_call_id=session_id,
            )
        )


def _write_interest_history(
    db: AsyncSession,
    lead_id: str,
    session_id: str | None,
    facts: dict[str, Any],
) -> None:
    """Append a LeadInterestHistory row if interest_level is present in facts.

    Always appends a new row — never updates existing rows (append-only).

    Args:
        db: Active async DB session.
        lead_id: UUID of the lead.
        session_id: UUID of the source call session (for FK + provenance).
        facts: Extracted facts dict from GPT.
    """
    interest_level = facts.get("interest_level")
    if interest_level is None:
        return

    # Clamp to 0-100 range (application-layer enforcement per spec)
    level = max(0, min(100, int(interest_level)))

    db.add(
        LeadInterestHistory(
            id=_new_uuid(),
            lead_id=lead_id,
            interest_level=level,
            source_call_id=session_id,
        )
    )
