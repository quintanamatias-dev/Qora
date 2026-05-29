"""QORA — Post-call summarizer and fact extractor.

Orchestrates per-dimension analysis: each module under
``app.analysis.universal`` owns its own prompt, schema, and OpenAI call.
This summarizer fans the 13 ``analyze`` coroutines out via
``asyncio.gather(return_exceptions=True)`` and merges the results into
``PostCallAnalysis``. One bad dimension does not kill the analysis — it is
logged and the field falls back to the schema's default.

Flow:
1. Load transcript turns for the session from DB.
2. If 0 turns → skip (no GPT calls, no side-effects).
3. Run all 13 dimensions in parallel; assemble PostCallAnalysis.
4. model_dump() → facts dict (summary popped out for separate persistence).
5. Persist summary + facts to CallSession + CallAnalysis.
6. Merge facts into Lead (objection union, latest values, do_not_call flag).

Failures are always caught and logged — MUST NOT raise, MUST NOT affect
session close or any other operation.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import structlog
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.schema import PostCallAnalysis
from app.analysis.universal import DIMENSION_MODULES
from app.analysis.universal.data_corrections import (
    DataCorrection,
    DataCorrectionsAxis,
    run_data_corrections_pipeline,
)
from app.analysis.universal.interest import run_interest_pipeline
from app.analysis.universal.misc_notes import (
    MiscNotesAxis,
    _coerce_current_notes,
    run_misc_notes_pipeline,
)
from app.analysis.universal.profile_facts import (
    ProfileFactsAxis,
    run_profile_facts_pipeline,
)
from app.calls.models import CallAnalysis, CallSession, TranscriptTurn
from app.leads.models import Lead, LeadInterestHistory, LeadProfileFact

logger = structlog.get_logger(__name__)

# Terminal states from which no further status transitions are allowed.
_TERMINAL_STATUSES: frozenset[str] = frozenset({"interested", "not_interested"})

# Negative close_lead outcome classifications → not_interested
_NEGATIVE_CLASSIFICATIONS: frozenset[str] = frozenset(
    {"completed_negative", "do_not_contact", "hostile"}
)


# ---------------------------------------------------------------------------
# Pure helper: next_action_result → lead status target
# ---------------------------------------------------------------------------


def apply_status_from_next_action(
    current_status: str,
    next_action_result: dict | None,
) -> str | None:
    """Map next_action_result to a target lead status.

    This is a pure function — no DB access, no side effects.
    Returns the target status string to apply, or None if no transition
    should be attempted.

    Rules (spec: lead-status-lifecycle):
    - Only applies when current_status == "called".
    - Terminal states (interested, not_interested) → None (no transition).
    - "new" / any other non-called state → None.
    - action == "close_lead":
        - outcome.classification == "completed_positive" → "interested"
        - outcome.classification in {completed_negative, do_not_contact, hostile} → "not_interested"
    - action in {"follow_up", "schedule_call"} → "follow_up"
    - action in {"retry_call", "human_review"} → None
    - Unknown/absent action → None

    Args:
        current_status: Lead.status value (string).
        next_action_result: Dict with "action" key (and optional "outcome" sub-dict).

    Returns:
        Target status string or None.
    """
    if current_status != "called":
        return None

    if not next_action_result or not isinstance(next_action_result, dict):
        return None

    action = next_action_result.get("action")

    if action == "close_lead":
        outcome = next_action_result.get("outcome") or {}
        classification = (
            outcome.get("classification") if isinstance(outcome, dict) else None
        )
        if classification == "completed_positive":
            return "interested"
        if classification in _NEGATIVE_CLASSIFICATIONS:
            return "not_interested"
        return None

    if action in ("follow_up", "schedule_call"):
        return "follow_up"

    # retry_call, human_review, or unknown → no change
    return None


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

    # Run all dimensions in parallel.
    # On failure (ALL dimensions blew up), persist a partial-analysis marker so
    # the record shows that analysis was attempted but failed.
    user_turns = sum(1 for t in turns if t.role == "user")
    agent_turns = sum(1 for t in turns if t.role == "agent")

    # qora-interest-pipeline: Load previous interest_level from Lead for 70/30 formula
    previous_interest_level: int | None = None
    if cs.lead_id:
        prev_result = await db.execute(
            select(Lead.interest_level).where(Lead.id == cs.lead_id)
        )
        previous_interest_level = prev_result.scalar_one_or_none()

    # qora-profile-facts Phase 3: Load current profile facts for stateful pipeline
    current_profile_facts: list[dict] = []
    if cs.lead_id:
        from app.leads.service import get_facts_by_namespace

        current_profile_facts = await get_facts_by_namespace(db, cs.lead_id, "profile:")

    # qora-misc-notes: Load previous misc_notes from Lead.extracted_facts for stateful pipeline
    # qora-data-corrections: also build current_lead_data snapshot for corrections pipeline
    # qora-next-action: also build LeadSnapshot + ClientRules for post-analysis pipeline
    current_misc_notes = []
    current_lead_data: dict = {}
    lead_snapshot: "Any | None" = None
    client_rules: "Any | None" = None
    if cs.lead_id:
        lead_result = await db.execute(select(Lead).where(Lead.id == cs.lead_id))
        lead_for_notes = lead_result.scalar_one_or_none()
        if lead_for_notes is not None:
            raw_facts = lead_for_notes.extracted_facts or {}
            if isinstance(raw_facts, str):
                try:
                    import json as _json

                    raw_facts = _json.loads(raw_facts)
                except Exception:
                    raw_facts = {}
            raw_misc = (
                raw_facts.get("misc_notes") if isinstance(raw_facts, dict) else None
            )
            current_misc_notes = _coerce_current_notes(raw_misc)

            # Build snapshot of correctable fields for the data corrections pipeline
            current_lead_data = {
                "name": lead_for_notes.name,
                "phone": lead_for_notes.phone,
                "email": lead_for_notes.email,
                "age": lead_for_notes.age,
                "car_make": lead_for_notes.car_make,
                "car_model": lead_for_notes.car_model,
                "car_year": lead_for_notes.car_year,
                "current_insurance": lead_for_notes.current_insurance,
            }

            # qora-next-action: build LeadSnapshot for post-analysis pipeline
            from app.analysis.universal.next_action import LeadSnapshot

            lead_snapshot = LeadSnapshot(
                call_count=lead_for_notes.call_count or 0,
                do_not_call=bool(lead_for_notes.do_not_call),
                last_called_at=lead_for_notes.last_called_at,
            )

    # qora-next-action: build ClientRules from Client config
    # qora-analysis-locale: also read analysis_language for locale-aware analysis
    analysis_language: str = "Spanish"  # safe default for all existing clients
    if cs.client_id:
        from app.tenants.models import Client as _Client

        client_row = await db.get(_Client, cs.client_id)
        if client_row is not None:
            from app.analysis.universal.next_action import ClientRules

            client_rules = ClientRules(
                max_attempts=client_row.next_action_max_attempts,
                min_interest_for_followup=client_row.next_action_min_interest_for_followup,
                close_on_hard_rejection=bool(
                    client_row.next_action_close_on_hard_rejection
                ),
                scheduler_cooldown_minutes=client_row.scheduler_cooldown_minutes,
                scheduler_allowed_hours_start=client_row.scheduler_allowed_hours_start,
                scheduler_allowed_hours_end=client_row.scheduler_allowed_hours_end,
                scheduler_timezone=client_row.scheduler_timezone,
            )
            # Read configured language; fall back to "Spanish" if column missing
            # (e.g. old DB without migration applied yet — graceful degradation).
            analysis_language = (
                getattr(client_row, "analysis_language", "Spanish") or "Spanish"
            )

    try:
        summary, facts = await _call_gpt_summarize(
            transcript_text,
            previous_interest_level=previous_interest_level,
            current_profile_facts=current_profile_facts,
            current_misc_notes=current_misc_notes,
            current_lead_data=current_lead_data,
            has_lead=bool(cs.lead_id),
            lead_snapshot=lead_snapshot,
            client_rules=client_rules,
            analysis_language=analysis_language,
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
            # DEPRECATED: cs.extracted_facts — use call_analyses table instead
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
    #
    # qora-data-corrections: pop data_corrections_structured BEFORE persisting extracted_facts.
    # DataCorrectionsAxis is a Pydantic model — not JSON-serializable by SQLAlchemy's JSON type.
    # It's consumed by _merge_facts_into_lead (which also sets facts["data_corrections"] to the
    # serializable list-of-dicts result), then discarded from the persisted dict.
    _corrections_axis = facts.pop("data_corrections_structured", None)

    async with db.begin_nested():
        # Persist to CallSession (legacy path)
        cs.summary = summary
        cs.total_user_turns = user_turns
        cs.total_agent_turns = agent_turns

        # Merge into Lead FIRST — _merge_facts_into_lead updates facts["data_corrections"]
        # to the serializable list-of-dicts audit result before we persist extracted_facts.
        if cs.lead_id:
            await _merge_facts_into_lead(
                db,
                cs.lead_id,
                summary,
                facts,
                session_id=cs.id,
                corrections_axis=_corrections_axis,
            )

        # DEPRECATED: cs.extracted_facts — use call_analyses table instead.
        # Kept for backward compat with any code that reads CallSession.extracted_facts.
        cs.extracted_facts = facts

        # ★ NEW: Dual-write to CallAnalysis (analysis v2 — same savepoint, atomic)
        await _upsert_call_analysis(db, cs.id, cs.lead_id, cs.client_id, summary, facts)

        # Auto-schedule follow-up call if eligible (Phase 6)
        if cs.lead_id and cs.client_id:
            await _auto_schedule_if_needed(db, cs, facts)

    # Fire-and-forget CRM sync hook (Phase 3 — airtable-crm-integration).
    # Only dispatched after the savepoint commits successfully (CS-1).
    # _schedule_crm_sync handles config-missing no-op internally (FM-4).
    if cs.lead_id and cs.client_id:
        await _schedule_crm_sync(
            client_id=cs.client_id,
            lead_id=cs.lead_id,
            db=db,
        )

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
    previous_interest_level: int | None = None,
    current_profile_facts: list[dict] | None = None,
    current_misc_notes: list | None = None,
    current_lead_data: dict | None = None,
    has_lead: bool = True,
    lead_snapshot: "Any | None" = None,
    client_rules: "Any | None" = None,
    analysis_language: str = "Spanish",
) -> tuple[str, dict[str, Any]]:
    """Run 6 universal dimensions, the 2-phase interest pipeline, profile facts pipeline,
    misc notes pipeline, data corrections pipeline, and post-analysis next_action pipeline.

    qora-interest-pipeline: The old monolithic 13-parallel gather is replaced by:
    - Phase 1: 6 independent dimensions in parallel via asyncio.gather
    - Phase 2: Interest pipeline (interests → interest_level sequential) via run_interest_pipeline
    - Phase 3: Profile facts pipeline (stateful) via run_profile_facts_pipeline
    - Phase 4: Misc notes pipeline (stateful) via run_misc_notes_pipeline
    - Phase 5: Data corrections pipeline (stateful) via run_data_corrections_pipeline

    qora-next-action: Post-analysis phase added after all parallel dimensions complete:
    - Phase 6: Next action pipeline (sequential) via run_next_action_pipeline

    All parallel phases run concurrently at the top level. Results are merged into PostCallAnalysis.

    Args:
        transcript_text: Formatted transcript string.
        previous_interest_level: Lead's prior interest score for 70/30 formula.
        current_profile_facts: Active profile facts from DB for stateful pipeline.
        current_misc_notes: Previous misc notes from Lead.extracted_facts for stateful pipeline.
        current_lead_data: Current lead field snapshot for data corrections pipeline.
        lead_snapshot: LeadSnapshot for next_action pipeline (call_count, do_not_call, etc.).
        client_rules: ClientRules for next_action pipeline (thresholds, scheduler config).
        analysis_language: Output language for customer-facing text fields (summaries,
            descriptions, evidence, reasons, notes). Canonical enum/code fields stay in
            English regardless of this setting. Defaults to "Spanish" for backward compat.

    Returns:
        Tuple of (summary_text, extracted_facts_dict).

    Raises:
        RuntimeError: When ALL 6 independent dimensions AND pipelines fail.
    """
    client, _model = _get_openai_client()
    facts_list = current_profile_facts or []
    notes_list = current_misc_notes or []
    lead_data = current_lead_data or {}

    if has_lead:
        # Run 7 independent dimensions + interest pipeline + profile pipeline
        # + misc notes pipeline + data corrections pipeline concurrently
        (
            independent_results_raw,
            pipeline_raw,
            profile_raw,
            misc_raw,
            corrections_raw,
        ) = await asyncio.gather(
            asyncio.gather(
                *[
                    mod.analyze(transcript_text, client, language=analysis_language)
                    for mod in DIMENSION_MODULES
                ],
                return_exceptions=True,
            ),
            run_interest_pipeline(
                transcript_text,
                client,
                previous_score=previous_interest_level,
                language=analysis_language,
            ),
            run_profile_facts_pipeline(
                transcript_text,
                client,
                current_facts=facts_list,
                language=analysis_language,
            ),
            run_misc_notes_pipeline(
                transcript_text,
                client,
                current_notes=notes_list,
                language=analysis_language,
            ),
            run_data_corrections_pipeline(
                transcript_text,
                client,
                current_lead_data=lead_data,
            ),
            return_exceptions=True,
        )
    else:
        # No lead_id: skip stateful pipelines (require context)
        profile_raw = ProfileFactsAxis()
        misc_raw = MiscNotesAxis()
        corrections_raw = DataCorrectionsAxis()
        independent_results_raw, pipeline_raw = await asyncio.gather(
            asyncio.gather(
                *[
                    mod.analyze(transcript_text, client, language=analysis_language)
                    for mod in DIMENSION_MODULES
                ],
                return_exceptions=True,
            ),
            run_interest_pipeline(
                transcript_text,
                client,
                previous_score=previous_interest_level,
                language=analysis_language,
            ),
            return_exceptions=True,
        )

    fields: dict[str, Any] = {}
    failures = 0

    # -------------------------------------------------------------------
    # Process 11 independent dimensions
    # -------------------------------------------------------------------
    if isinstance(independent_results_raw, Exception):
        # The inner gather itself failed (extremely rare)
        failures += len(DIMENSION_MODULES)
        logger.error(
            "dimension_gather_failed",
            error=str(independent_results_raw),
            error_type=type(independent_results_raw).__name__,
        )
    else:
        for mod, result in zip(DIMENSION_MODULES, independent_results_raw):
            dim_name = mod.DIMENSION["name"]
            if isinstance(result, Exception):
                failures += 1
                logger.error(
                    "dimension_analysis_failed",
                    dimension=dim_name,
                    error=str(result),
                    error_type=type(result).__name__,
                )
                continue
            fields[mod.DIMENSION["target_field"]] = result

    # -------------------------------------------------------------------
    # Process interest pipeline result
    # -------------------------------------------------------------------
    if isinstance(pipeline_raw, Exception):
        # run_interest_pipeline itself raised (should not happen — it catches internally)
        failures += 1
        logger.error(
            "interest_pipeline_exception",
            error=str(pipeline_raw),
            error_type=type(pipeline_raw).__name__,
        )
        # Leave interest_level and detected_interests at schema defaults (0 / empty)
    else:
        interests_result, level_result = pipeline_raw

        # Check if Agent 1 (interests) returned an error dict
        interests_is_error = (
            isinstance(interests_result, dict) and "error" in interests_result
        )
        level_is_error = isinstance(level_result, dict) and "error" in level_result

        if interests_is_error:
            # Agent 1 failed — store error in extra_axes_data, leave fields at defaults
            failures += 1
            logger.error(
                "interest_pipeline_failed",
                interests_error=interests_result.get("error"),
                level_error=level_result.get("error") if level_is_error else None,
            )
            fields.setdefault("extra_axes_data", {})
            fields["extra_axes_data"]["interest_pipeline_error"] = {
                "interests": interests_result,
                "interest_level": level_result,
            }
            # Fields stay at schema defaults (InterestsAxis(), 0)
        else:
            # Agent 1 succeeded — set detected_interests
            fields["detected_interests"] = interests_result

            if level_is_error:
                # Agent 2 failed — store error marker, keep interests result
                logger.error(
                    "interest_level_pipeline_failed",
                    error=level_result.get("error"),
                )
                fields.setdefault("extra_axes_data", {})
                fields["extra_axes_data"]["interest_pipeline_error"] = {
                    "interest_level": level_result,
                }
                # interest_level stays at schema default (0)
            else:
                # Both agents succeeded — extract int score for interest_level field
                from app.analysis.universal.interest.interest_level import (
                    InterestLevelResult,
                )

                if isinstance(level_result, InterestLevelResult):
                    fields["interest_level"] = level_result.general_score
                    # Store rich detail in extra_axes_data for monitoring/analytics
                    fields.setdefault("extra_axes_data", {})
                    fields["extra_axes_data"]["interest_pipeline"] = (
                        level_result.model_dump()
                    )
                else:
                    fields["interest_level"] = 0

    # -------------------------------------------------------------------
    # Process profile facts pipeline result
    # -------------------------------------------------------------------
    if isinstance(profile_raw, Exception):
        # Profile facts pipeline raised unexpectedly — non-critical, log and use empty axis
        logger.error(
            "profile_facts_pipeline_exception",
            error=str(profile_raw),
            error_type=type(profile_raw).__name__,
        )
        fields["profile_facts"] = ProfileFactsAxis()
    else:
        # Profile pipeline always returns ProfileFactsAxis (never raises — catches internally)
        fields["profile_facts"] = (
            profile_raw
            if isinstance(profile_raw, ProfileFactsAxis)
            else ProfileFactsAxis()
        )

    # -------------------------------------------------------------------
    # Process misc notes pipeline result (qora-misc-notes)
    # -------------------------------------------------------------------
    if isinstance(misc_raw, Exception):
        # Misc notes pipeline raised unexpectedly — non-critical, log and use empty axis
        logger.error(
            "misc_notes_pipeline_exception",
            error=str(misc_raw),
            error_type=type(misc_raw).__name__,
        )
        fields["misc_notes"] = MiscNotesAxis()
    else:
        # Misc notes pipeline always returns MiscNotesAxis (never raises — catches internally)
        fields["misc_notes"] = (
            misc_raw if isinstance(misc_raw, MiscNotesAxis) else MiscNotesAxis()
        )

    # -------------------------------------------------------------------
    # Process data corrections pipeline result (qora-data-corrections)
    # -------------------------------------------------------------------
    if isinstance(corrections_raw, Exception):
        # Data corrections pipeline raised unexpectedly — non-critical, use empty axis
        logger.error(
            "data_corrections_pipeline_exception",
            error=str(corrections_raw),
            error_type=type(corrections_raw).__name__,
        )
        fields["data_corrections_structured"] = DataCorrectionsAxis()
    else:
        # run_data_corrections_pipeline never raises (catches internally) — always DataCorrectionsAxis
        fields["data_corrections_structured"] = (
            corrections_raw
            if isinstance(corrections_raw, DataCorrectionsAxis)
            else DataCorrectionsAxis()
        )

    if failures >= len(DIMENSION_MODULES) + 1:  # 6 + interest pipeline (counts as 1)
        raise RuntimeError(
            f"all {failures} dimension analyses failed — see dimension_analysis_failed logs"
        )

    # -------------------------------------------------------------------
    # Post-analysis Phase 6: next_action pipeline (qora-next-action)
    # Runs sequentially AFTER all parallel dimensions complete.
    # Receives structured dimension outputs + lead state + client rules.
    # Only runs when lead_snapshot and client_rules are available.
    # -------------------------------------------------------------------
    if lead_snapshot is not None and client_rules is not None:
        try:
            from app.analysis.universal.next_action import (
                NextActionContext,
                run_next_action_pipeline,
            )
            from app.analysis.universal.commitments import CommitmentsAxis as _CA
            from app.analysis.universal.objections import ObjectionsAxis as _OA
            from app.analysis.universal.outcome import CallOutcome as _CO
            from app.analysis.universal.problem import ProblemAxis as _PA

            # Extract dimension outputs (use defaults if dimensions failed)
            raw_outcome = fields.get("call_outcome")
            ctx_outcome = (
                raw_outcome
                if isinstance(raw_outcome, _CO)
                else _CO(
                    classification="no_answer",
                    reason="dimension failed",
                    confidence="low",
                )
            )
            ctx_interest = int(fields.get("interest_level") or 0)
            raw_commitments = fields.get("commitments")
            ctx_commitments = (
                raw_commitments if isinstance(raw_commitments, _CA) else _CA()
            )
            raw_objections = fields.get("objections")
            ctx_objections = (
                raw_objections if isinstance(raw_objections, _OA) else _OA()
            )
            raw_problem = fields.get("identified_problem")
            ctx_problem = (
                raw_problem if isinstance(raw_problem, _PA) else _PA(pain_points=[])
            )

            na_ctx = NextActionContext(
                outcome=ctx_outcome,
                interest_level=ctx_interest,
                commitments=ctx_commitments,
                objections=ctx_objections,
                problem=ctx_problem,
                lead=lead_snapshot,
                client=client_rules,
            )
            na_result = await run_next_action_pipeline(na_ctx, client)
            fields["next_action_suggested"] = na_result.action
            fields["next_action_result"] = na_result.model_dump()
        except Exception as na_exc:
            logger.error(
                "next_action_pipeline_exception",
                error=str(na_exc),
                error_type=type(na_exc).__name__,
            )
            # Non-critical — fall through with default "wait" from PostCallAnalysis schema

    analysis = PostCallAnalysis(**fields)

    # model_dump() gives us the full structured facts dict.
    facts = analysis.model_dump()

    # Pop summary out — it's stored separately on CallSession.
    summary = str(facts.pop("summary", ""))

    # qora-next-action: re-inject next_action_result into facts dict
    # (PostCallAnalysis.model_dump() will include it if it was set in fields,
    # but we also need it accessible as "next_action_result" key for scheduler reads)
    if fields.get("next_action_result") is not None:
        facts["next_action_result"] = fields["next_action_result"]

    # qora-data-corrections: inject structured corrections into facts dict
    # (not in PostCallAnalysis model — passed as a side-channel key)
    _dc_structured = fields.get("data_corrections_structured")
    if _dc_structured is not None:
        facts["data_corrections_structured"] = _dc_structured

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
    corrections_axis: "DataCorrectionsAxis | None" = None,
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

    ★ NEW (qora-data-corrections):
    - Structured corrections applied via _apply_structured_corrections
    - Corrections stored in facts["data_corrections"] as list-of-dicts for audit

    Args:
        db: Active async DB session.
        lead_id: UUID of the lead to update.
        summary: Call summary text.
        facts: Extracted facts dict from GPT (already model_dump()'d).
        session_id: Optional UUID of the source call session (for FK reference).
        corrections_axis: Optional DataCorrectionsAxis from run_data_corrections_pipeline.
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

    raw_objections = (facts.get("objections") or {}).get("objections") or []
    new_objections = [
        o["category"]
        for o in raw_objections
        if isinstance(o, dict) and o.get("category")
    ]
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

    # do_not_call ← True if suggested via close_lead action OR via do_not_contact classification
    # qora-next-action: old "do_not_call" action replaced by "close_lead" from NextActionResult
    if facts.get("next_action_suggested") in ("close_lead", "do_not_call"):
        lead.do_not_call = True
    call_outcome = facts.get("call_outcome") or {}
    if call_outcome.get("classification") == "do_not_contact":
        lead.do_not_call = True

    # qora-next-action: set Lead.next_action_at from NextActionResult.next_action_at
    next_action_result = facts.get("next_action_result") or {}
    if isinstance(next_action_result, dict):
        nat = next_action_result.get("next_action_at")
        if nat is not None:
            from datetime import datetime as _dt, timezone as _tz

            if isinstance(nat, str):
                try:
                    # Parse ISO format string
                    parsed_nat = _dt.fromisoformat(nat)
                    if parsed_nat.tzinfo is None:
                        parsed_nat = parsed_nat.replace(tzinfo=_tz.utc)
                    lead.next_action_at = parsed_nat
                except ValueError:
                    pass
            elif isinstance(nat, _dt):
                lead.next_action_at = nat

    # next_action ← latest suggested action
    if facts.get("next_action_suggested"):
        lead.next_action = facts["next_action_suggested"]

    # configurable-agent-tools Phase 2: apply status transitions from next_action_result.
    # Only transitions when lead.status == "called"; terminal states are guarded in
    # apply_status_from_next_action (returns None → no transition attempted).
    _next_action_result_for_status = facts.get("next_action_result")
    _target_status = apply_status_from_next_action(
        current_status=lead.status,
        next_action_result=_next_action_result_for_status,
    )
    if _target_status is not None:
        from app.leads.service import transition_lead_status as _transition

        try:
            await _transition(db, lead_id, _target_status)
            logger.info(
                "summarizer_status_transitioned",
                lead_id=lead_id,
                from_status=lead.status,
                to_status=_target_status,
            )
        except Exception as _exc:
            logger.warning(
                "summarizer_status_transition_failed",
                lead_id=lead_id,
                target_status=_target_status,
                error=str(_exc),
            )

    # qora-data-corrections: apply structured corrections from pipeline
    # corrections_axis is DataCorrectionsAxis from run_data_corrections_pipeline;
    # _apply_structured_corrections uses CORRECTABLE_FIELDS registry to set lead attrs.
    if corrections_axis is not None and isinstance(
        corrections_axis, DataCorrectionsAxis
    ):
        all_corrections = _apply_structured_corrections(
            lead, corrections_axis.corrections
        )
        # Store ALL corrections in facts (applied + rejected) for full audit trail
        facts["data_corrections"] = [c.model_dump() for c in all_corrections]
        # Write LeadProfileFact rows for APPLIED corrections only (not rejected)
        actually_applied = [c for c in all_corrections if c.applied]
        if actually_applied:
            await _write_structured_correction_facts(
                db, lead_id, session_id, actually_applied
            )
    else:
        facts["data_corrections"] = []

    # ★ NEW: Dual-write to relational tables (analysis v2)
    await _write_lead_profile_facts(db, lead_id, session_id, facts)
    _write_interest_history(db, lead_id, session_id, facts)

    # qora-profile-facts Phase 3: Write profile: facts with hard DELETE semantics
    # (separate from _LIST_AXES which uses supersede pattern for other namespaces)
    await _write_profile_facts_from_pipeline(db, lead_id, session_id, facts)


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


async def _schedule_crm_sync(
    client_id: str,
    lead_id: str,
    db: AsyncSession,
) -> None:
    """Dispatch an optional fire-and-forget CRM sync task after savepoint commits.

    This is a generic post-call integration hook — it knows nothing about
    Airtable or any specific CRM adapter. Provider-specific behaviour lives
    inside ``app/integrations/adapters/``.

    Behaviour:
    - Schedules a background coroutine that opens its OWN DB session and runs
      ``crm_sync_service.sync_lead`` (CS-2). The caller's ``db`` session is NOT
      forwarded to the task — it would be closed by the time the fire-and-forget
      task runs, causing ``sync_lead`` to fail with a closed-session error.
      This mirrors ``_summarize_in_background`` in app/calls/service.py.
    - If the client has no ``crm.yaml``, sync_lead returns silently (FM-4).
    - If the CRM sync task fails internally it logs and swallows the error (CS-5).
    - This function itself must NEVER raise — any unexpected error is caught here.

    Args:
        client_id: Client slug used to locate the client's ``crm.yaml``.
        lead_id: UUID of the lead to push to the CRM.
        db: Active async DB session of the caller. Intentionally NOT passed to the
            background task — kept in the signature for backward-compat. The task
            opens its own independent session.
    """
    try:
        asyncio.create_task(_run_crm_sync_in_background(client_id, lead_id))
    except Exception as exc:
        logger.warning(
            "crm_sync_dispatch_failed",
            client_id=client_id,
            lead_id=lead_id,
            error=str(exc),
        )


async def _run_crm_sync_in_background(client_id: str, lead_id: str) -> None:
    """Background task: run CRM sync in an independent DB session.

    Opens a fresh ``get_session()`` so the fire-and-forget CRM push does not
    depend on the caller's session, which is closed once the summarizer's
    request context unwinds. Any failure is logged and swallowed — the CRM is a
    downstream mirror only and must never affect the post-call analysis (CS-5).

    Args:
        client_id: Client slug used to locate the client's ``crm.yaml``.
        lead_id: UUID of the lead to push to the CRM.
    """
    from app.core.database import get_session
    from app.integrations import crm_sync_service

    try:
        async with get_session() as db:
            await crm_sync_service.sync_lead(
                client_id=client_id,
                lead_id=lead_id,
                db_session=db,
            )
    except Exception as exc:
        logger.warning(
            "crm_sync_background_failed",
            client_id=client_id,
            lead_id=lead_id,
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
# Structured corrections application (qora-data-corrections)
# ---------------------------------------------------------------------------


def _apply_structured_corrections(
    lead: "Lead",
    corrections: list["DataCorrection"],
) -> list["DataCorrection"]:
    """Apply structured corrections from run_data_corrections_pipeline to a Lead.

    Uses CORRECTABLE_FIELDS registry to coerce values and setattr atomically.
    Only corrections with applied=True are written to the Lead.
    Idempotency: skips if corrected_value equals current value (already handled
    by the pipeline, but double-checked here as a safety gate).

    Args:
        lead: Lead ORM instance to update in-place.
        corrections: List of DataCorrection items from the pipeline.

    Returns:
        ALL DataCorrection items (applied=True and applied=False) for the audit
        trail stored in facts["data_corrections"]. Only applied=True items are
        written to the Lead. Rejected items are preserved with their rejection_reason.
    """
    from app.analysis.universal.data_corrections import CORRECTABLE_FIELDS, coerce_value

    all_corrections: list[DataCorrection] = []
    for correction in corrections:
        if not correction.applied:
            # Rejected (validation failure, confidence gate, etc.) — include in audit
            all_corrections.append(correction)
            continue
        field = correction.field
        if field not in CORRECTABLE_FIELDS:
            continue  # Safety: unknown field should have been dropped by pipeline
        entry = CORRECTABLE_FIELDS[field]
        try:
            coerced = coerce_value(correction.corrected_value, entry.type)
            setattr(lead, entry.lead_attr, coerced)
            all_corrections.append(correction)
            logger.info(
                "data_correction_applied",
                field=field,
                lead_attr=entry.lead_attr,
                corrected_value=correction.corrected_value,
                confidence=correction.confidence,
            )
        except (ValueError, TypeError) as exc:
            logger.warning(
                "data_correction_coerce_failed",
                field=field,
                corrected_value=correction.corrected_value,
                error=str(exc),
            )
            # Coercion failed — include in audit as rejected
            from app.analysis.universal.data_corrections import DataCorrection as _DC

            all_corrections.append(
                _DC(
                    field=correction.field,
                    current_value=correction.current_value,
                    corrected_value=correction.corrected_value,
                    confidence=correction.confidence,
                    evidence=correction.evidence,
                    applied=False,
                    rejection_reason=f"coercion failed: {exc}",
                )
            )
    return all_corrections


async def _write_structured_correction_facts(
    db: AsyncSession,
    lead_id: str,
    session_id: str | None,
    corrections: list["DataCorrection"],
) -> None:
    """Write LeadProfileFact rows for each applied structured correction.

    Upsert semantics: supersedes any existing active row for the same fact_key
    when the value changes. Confidence is preserved from the DataCorrection item.

    Args:
        db: Active async DB session.
        lead_id: UUID of the lead.
        session_id: UUID of the source call session (FK + provenance).
        corrections: Applied DataCorrection items (applied=True only).
    """
    from datetime import datetime, timezone

    if not corrections:
        return

    now = datetime.now(timezone.utc)

    for correction in corrections:
        fact_key = correction.field
        fact_value = str(correction.corrected_value)

        # Supersede existing active row if value differs
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
                continue  # Same value — skip
            existing.superseded_at = now

        db.add(
            LeadProfileFact(
                id=_new_uuid(),
                lead_id=lead_id,
                fact_key=fact_key,
                fact_value=fact_value,
                source_call_id=session_id,
            )
        )


# ---------------------------------------------------------------------------
# Analysis v2 helpers — dual-write to relational tables
# ---------------------------------------------------------------------------


def _new_uuid() -> str:
    """Generate a new UUID4 string (matches project PK convention)."""
    return str(uuid.uuid4())


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
    ca.outcome_reason = call_outcome.get("reason")
    _primary_pain = _get_primary_pain(identified_problem)
    ca.urgency = _str_or_none(_primary_pain.get("urgency")) if _primary_pain else None
    ca.primary_need = _primary_pain.get("description") if _primary_pain else None
    ca.next_action_suggested = facts.get("next_action_suggested")
    ca.current_insurance = facts.get("current_insurance")
    # qora-data-corrections: structured corrections are now a list of dicts — serialize to JSON
    _dc_data = facts.get("data_corrections")
    if isinstance(_dc_data, list):
        ca.data_corrections = json.dumps(_dc_data) if _dc_data else "[]"
    else:
        # Legacy fallback: string-based corrections (pre-migration data or empty)
        ca.data_corrections = str(_dc_data) if _dc_data else "[]"
    # qora-misc-notes: misc_notes is now MiscNotesAxis — serialize as JSON (same as profile_facts)
    _mn_data = facts.get("misc_notes") or {}
    ca.misc_notes = json.dumps(_mn_data) if _mn_data else json.dumps({"notes": []})
    ca.objections = _to_json_list((facts.get("objections") or {}).get("objections"))
    # qora-interest-pipeline: detected_interests now uses InterestsAxis (items: list[InterestItem])
    # Extract product IDs from items for the products column (backward compat)
    items = detected_interests.get("items") or []
    products_list = [
        item["product"]
        for item in items
        if isinstance(item, dict) and item.get("product")
    ]
    ca.products = _to_json_list(products_list)
    # specific_needs: flatten all needs from all items
    specific_needs_flat = []
    for item in items:
        if isinstance(item, dict):
            specific_needs_flat.extend(item.get("needs") or [])
    ca.specific_needs = _to_json_list(list(dict.fromkeys(specific_needs_flat)))  # dedup
    # buying_signals: no longer in InterestsAxis — set to empty list
    ca.buying_signals = _to_json_list([])
    ca.pain_points = _to_json_list(identified_problem.get("pain_points"))
    # Issue #35 — 4 new universal axes
    ca.service_issues = _to_json_list((facts.get("service_issues") or {}).get("issues"))
    # qora-profile-facts Phase 3: serialize pipeline updates to JSON.
    # facts["profile_facts"] = {"updates": [list of ProfileFactUpdate dicts]}
    # (set from run_profile_facts_pipeline result via fields["profile_facts"]).
    _pf_data = facts.get("profile_facts") or {}
    ca.profile_facts = _to_json_list(_pf_data.get("updates") or [])
    ca.commitment_signals = _to_json_list(
        [
            c.get("description", "")
            for c in (facts.get("commitments") or {}).get("commitments") or []
        ]
    )
    # qora-abandonment: abandonment_reason is DEPRECATED (AD-4), set NULL for new records.
    # was_abrupt + abandonment_trigger are read from call_outcome dict.
    ca.abandonment_reason = None
    ca.was_abrupt = call_outcome.get("was_abrupt")
    ca.abandonment_trigger = call_outcome.get("abandonment_trigger")
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


def _get_primary_pain(identified_problem: dict) -> dict | None:
    """Find the primary PainPoint from identified_problem dict, or None if absent.

    Looks for the first PainPoint with is_primary=True. If none marked, returns
    the first pain point in the list (fallback). Returns None for empty lists.
    """
    pains = identified_problem.get("pain_points") or []
    for p in pains:
        if isinstance(p, dict) and p.get("is_primary"):
            return p
    # If no explicit primary, fall back to first item if available
    if pains and isinstance(pains[0], dict):
        return pains[0]
    return None


def _str_or_none(value: Any) -> str | None:
    """Return string representation of value, or None if value is None.

    Handles enum values by extracting .value (Pydantic model_dump() may return
    enum objects when mode='python' is used — the default).
    """
    if value is None:
        return None
    # Handle enum-like values that expose .value
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _to_json_list(value: Any) -> str:
    """Serialize value to a JSON list string. Returns '[]' if None or not a list."""
    if isinstance(value, list):
        return json.dumps(value)
    return "[]"


def _pain_point_key(raw_item: Any) -> str | None:
    """Normalize pain point payloads to one analytics/profile key.

    New payloads store structured PainPoint dicts (category + description).
    Legacy payloads may still be plain strings — keep supporting them.
    Uses category as the primary key for dedup/aggregation.
    """
    if isinstance(raw_item, dict):
        # Prefer category for consistent dedup across calls
        category = raw_item.get("category")
        if category and str(category).strip():
            return str(category).strip().lower()
        # Fall back to description snippet if no category
        description = raw_item.get("description")
        if description and str(description).strip():
            return str(description).strip().lower()[:80]  # cap at 80 chars
        return None
    if not raw_item or not str(raw_item).strip():
        return None
    return str(raw_item).strip().lower()


def _service_issue_key(raw_item: Any) -> str | None:
    """Normalize service issue payloads to one analytics/profile key.

    New payloads store structured objects. Persist their category for aggregation.
    Legacy payloads may still be plain strings, so keep supporting them.
    """
    if isinstance(raw_item, dict):
        category = raw_item.get("category")
        if category and str(category).strip():
            return str(category).strip().lower()
        description = raw_item.get("description")
        if description and str(description).strip():
            return str(description).strip().lower()
        return None
    if not raw_item or not str(raw_item).strip():
        return None
    return str(raw_item).strip().lower()


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

    _primary = _get_primary_pain(identified_problem)
    pn = _primary.get("description") if _primary else None
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
    # Axes: pain_points, service_issues.issues, commitments.commitments (descriptions),
    #       detected_interests.buying_signals, objections
    # Dedup: normalized (strip().lower()) fact_key match against active rows
    # qora-profile-facts Phase 3: profile: namespace is REMOVED from _LIST_AXES.
    # It is now handled exclusively by _write_profile_facts_from_pipeline()
    # which uses hard DELETE semantics (no superseded_at).
    _commitment_descriptions = [
        c.get("description", "")
        for c in (facts.get("commitments") or {}).get("commitments") or []
        if c.get("description")
    ]
    _LIST_AXES: list[tuple[str, list[Any]]] = [
        ("pain:", (facts.get("identified_problem") or {}).get("pain_points") or []),
        ("service_issue:", (facts.get("service_issues") or {}).get("issues") or []),
        ("objection:", (facts.get("objections") or {}).get("objections") or []),
        ("signal:", _commitment_descriptions),
        (
            "buying_signal:",
            [],  # qora-interest-pipeline: buying_signals removed from InterestsAxis
        ),
    ]

    for namespace_prefix, items in _LIST_AXES:
        if not items:
            continue
        for raw_item in items:
            if namespace_prefix == "service_issue:":
                normalized = _service_issue_key(raw_item)
            elif namespace_prefix == "objection:":
                normalized = _service_issue_key(raw_item)
            elif namespace_prefix == "pain:":
                normalized = _pain_point_key(raw_item)
            else:
                if not raw_item or not str(raw_item).strip():
                    continue
                normalized = str(raw_item).strip().lower()
            if not normalized:
                continue
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


def _slugify(text: str, max_len: int = 60) -> str:
    """Convert fact text to a stable slug for use in fact_key.

    Lowercase, strips non-alphanumeric chars (keeps hyphens), max 60 chars.
    """
    import re

    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9\-áéíóúüñàèìòùâêîôûäëïöü]", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:max_len]


async def _find_active_profile_fact_by_key(
    db: AsyncSession,
    lead_id: str,
    fact_key: str,
) -> "LeadProfileFact | None":
    """Find an active LeadProfileFact row by exact fact_key for a given lead.

    Returns the row or None if not found / already superseded.
    """
    result = await db.execute(
        select(LeadProfileFact).where(
            LeadProfileFact.lead_id == lead_id,
            LeadProfileFact.fact_key == fact_key,
            LeadProfileFact.superseded_at == None,  # noqa: E711
        )
    )
    return result.scalar_one_or_none()


async def _write_profile_facts_from_pipeline(
    db: AsyncSession,
    lead_id: str,
    session_id: str | None,
    facts: dict[str, Any],
) -> None:
    """Write LeadProfileFact rows for profile_facts pipeline results.

    Uses HARD DELETE semantics (no superseded_at) — per qora-profile-facts AD-3:
    - ADD: INSERT new row with fact_key='profile:{category}:{slug}', fact_value=JSON
    - UPDATE: DELETE old row (hard delete) + INSERT new row
    - REMOVE: DELETE old row (hard delete), no new insert

    Invalid target_fact_id for UPDATE → demote to ADD (GPT hallucinated ID).
    Invalid target_fact_id for REMOVE → silently discard.

    Args:
        db: Active async DB session.
        lead_id: UUID of the lead.
        session_id: UUID of the source call session (for FK + provenance).
        facts: model_dump()'d PostCallAnalysis facts dict.
    """
    pf_raw = facts.get("profile_facts") or {}
    updates_raw = pf_raw.get("updates") or []

    if not updates_raw:
        return

    for upd in updates_raw:
        if not isinstance(upd, dict):
            continue
        operation = upd.get("operation")
        category = upd.get("category")
        fact_text = upd.get("fact") or ""
        evidence = upd.get("evidence") or ""
        confidence = upd.get("confidence") or "medium"
        target_fact_id = upd.get("target_fact_id")

        if not operation or not category or not fact_text:
            continue

        # Handle enum values from Python-mode model_dump() (ProfileFactCategory is str enum)
        category_str = category.value if hasattr(category, "value") else str(category)
        slug = _slugify(fact_text)
        new_key = f"profile:{category_str}:{slug}"
        new_value = json.dumps(
            {
                "category": category_str,
                "fact": fact_text,
                "evidence": evidence,
                "confidence": confidence,
            },
            ensure_ascii=False,
        )

        if operation == "add":
            db.add(
                LeadProfileFact(
                    id=_new_uuid(),
                    lead_id=lead_id,
                    fact_key=new_key,
                    fact_value=new_value,
                    source_call_id=session_id,
                )
            )

        elif operation == "update":
            if target_fact_id:
                existing = await _find_active_profile_fact_by_key(
                    db, lead_id, target_fact_id
                )
                if existing:
                    # Hard DELETE the old row — no superseded_at
                    await db.delete(existing)
                    await db.flush()
                # INSERT new row (both when found and as fallback for hallucinated ID)
            db.add(
                LeadProfileFact(
                    id=_new_uuid(),
                    lead_id=lead_id,
                    fact_key=new_key,
                    fact_value=new_value,
                    source_call_id=session_id,
                )
            )

        elif operation == "remove":
            if target_fact_id:
                existing = await _find_active_profile_fact_by_key(
                    db, lead_id, target_fact_id
                )
                if existing:
                    # Hard DELETE — no new insert
                    await db.delete(existing)
                    await db.flush()
                # else: invalid target_fact_id → silently discard


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
