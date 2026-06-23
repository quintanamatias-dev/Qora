"""QORA Calls — Router for call session lifecycle and transcript inspection.

Provides:
- GET  /{session_id}            — inspect a call session
- GET  /{session_id}/transcript — inspect transcript turns
- GET  /{session_id}/analysis   — inspect call analysis (all 12 dimensions)
- POST /{session_id}/end        — close a session (CAP-2a)
- POST /elevenlabs-postcall     — ElevenLabs post-call webhook (CAP-2b)

Covers: T3.5 admin/debug router + Phase 2a session lifecycle.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException

from app.calls.schemas import (
    CallAnalysisResponse,
    CallMetricsResponse,
    ElevenLabsPostCallPayload,
    EndSessionRequest,
    EndSessionResponse,
    MetricsPeriod,
    SessionTranscriptResponse,
    TranscriptTurnResponse,
)
from app.calls.service import (
    _schedule_summarize,
    add_transcript_turn,
    close_session,
    get_call_analysis,
    get_call_metrics,
    get_session,
    get_session_by_elevenlabs_id,
    get_transcript,
    list_sessions_for_client,
)
from app.core.auth import require_api_key
from app.core.database import get_session as db_session

router = APIRouter(prefix="/calls", tags=["calls"])

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Metrics endpoint — MUST be registered BEFORE /{session_id} routes
# (FastAPI matches first-registered; "metrics" would be parsed as a session_id UUID otherwise)
# ---------------------------------------------------------------------------


@router.get("/metrics", response_model=CallMetricsResponse, dependencies=[Depends(require_api_key)])
async def get_call_metrics_endpoint(
    client_id: str,
    lead_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
):
    """Return aggregated call metrics for a client.

    Query parameters:
    - **client_id** (required): Tenant client id to scope results.
    - **lead_id** (optional): Filter to a specific lead.
    - **date_from** (optional): Lower bound on call start time (inclusive).
    - **date_to** (optional): Upper bound on call start time (inclusive).
    """
    async with db_session() as db:
        metrics = await get_call_metrics(
            db,
            client_id=client_id.lower(),
            lead_id=lead_id,
            date_from=date_from,
            date_to=date_to,
        )

    return CallMetricsResponse(
        **metrics,
        period=MetricsPeriod(date_from=date_from, date_to=date_to),
    )


# ---------------------------------------------------------------------------
# Session serializer helper — shared by list and detail endpoints
# ---------------------------------------------------------------------------


def _session_to_dict(cs) -> dict:
    """Serialize a CallSession ORM object to a response dict.

    Includes summary and extracted_facts for CRM use.
    """
    return {
        "id": cs.id,
        "client_id": cs.client_id,
        "lead_id": cs.lead_id,
        "status": cs.status,
        "outcome": cs.outcome,
        "closed_reason": cs.closed_reason,
        "started_at": cs.started_at.isoformat() if cs.started_at else None,
        "ended_at": cs.ended_at.isoformat() if cs.ended_at else None,
        "duration_seconds": cs.duration_seconds,
        "billable_minutes": cs.billable_minutes,
        "total_user_turns": cs.total_user_turns,
        "total_agent_turns": cs.total_agent_turns,
        "summary": cs.summary,
        "extracted_facts": cs.extracted_facts,
        "merged_into_session_id": cs.merged_into_session_id,
    }


# ---------------------------------------------------------------------------
# List sessions endpoint — MUST be registered BEFORE /{session_id} routes
# ---------------------------------------------------------------------------


@router.get("", dependencies=[Depends(require_api_key)])
async def list_call_sessions(
    client_id: str,
    lead_id: str | None = None,
):
    """List all call sessions for a client, optionally filtered by lead.

    Query parameters:
    - **client_id** (required): Tenant client id to scope results.
    - **lead_id** (optional): Filter to a specific lead.

    Returns sessions ordered by started_at descending (most recent first).
    """
    async with db_session() as db:
        sessions = await list_sessions_for_client(db, client_id.lower(), lead_id)

    # Filter out ghost sessions: "initiated" with no turns and no duration.
    # These are WebSocket connection attempts that never established a real call.
    return [
        _session_to_dict(cs)
        for cs in sessions
        if not (
            cs.status == "initiated"
            and not cs.duration_seconds
            and not cs.total_user_turns
            and not cs.total_agent_turns
        )
    ]


# ---------------------------------------------------------------------------
# ElevenLabs post-call webhook — MUST be registered BEFORE /{session_id} routes
# ---------------------------------------------------------------------------


@router.post("/elevenlabs-postcall")
async def elevenlabs_postcall_webhook(body: ElevenLabsPostCallPayload):
    """Handle ElevenLabs post-call webhook (CAP-2b).

    - If session is `initiated`: close it with reason="network_drop" and increment Lead.call_count.
    - If session is `completed`: merge transcript turns if ElevenLabs has more data.
    - Idempotent on session status.
    """
    async with db_session() as db:
        cs = await get_session_by_elevenlabs_id(db, body.conversation_id)

        if cs is None:
            logger.warning(
                "postcall_unknown_conversation",
                conversation_id=body.conversation_id,
            )
            raise HTTPException(
                status_code=404,
                detail=f"No session found for conversation_id={body.conversation_id!r}",
            )

        el_transcript = body.transcript or []

        if cs.status == "initiated":
            # Session was never closed — close it now
            await close_session(
                db,
                session_id=cs.id,
                closed_reason="network_drop",
                update_lead_counters=True,
            )
            logger.info(
                "postcall_closed_orphan_session",
                session_id=cs.id,
                conversation_id=body.conversation_id,
                el_turn_count=len(el_transcript),
            )

        elif cs.status == "completed":
            # Already closed — check if ElevenLabs has more transcript turns to merge
            existing_turns = await get_transcript(db, cs.id)
            if el_transcript and len(el_transcript) > len(existing_turns):
                # Merge extra turns from ElevenLabs
                extra_turns = el_transcript[len(existing_turns) :]
                for turn_data in extra_turns:
                    role = turn_data.get("role", "unknown")
                    content = turn_data.get("message", "")
                    if content:
                        await add_transcript_turn(db, cs.id, role, content)
                logger.info(
                    "postcall_merged_transcript",
                    session_id=cs.id,
                    merged_count=len(extra_turns),
                )
                # Trigger re-summary with the full (merged) transcript (CAP-4)
                _schedule_summarize(cs.id, client_id=cs.client_id)
        else:
            # abandoned or other status — close to completed
            logger.info(
                "postcall_closing_non_initiated_session",
                session_id=cs.id,
                current_status=cs.status,
            )

    return {"status": "ok", "session_id": cs.id}


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


@router.post("/{conversation_id}/end", response_model=EndSessionResponse, dependencies=[Depends(require_api_key)])
async def end_call_session(conversation_id: str, body: EndSessionRequest):
    """Close a call session (CAP-2a).

    The path parameter `conversation_id` is the ElevenLabs conversation ID.
    Falls back to internal session UUID lookup if no ElevenLabs match is found.

    Idempotent: if session is already completed, returns 200 without double-incrementing.
    Sets status="completed", ended_at, duration_seconds, billable_minutes, closed_reason.
    Increments Lead.call_count and Lead.last_called_at — only on first close.
    """
    # T30 / REQ-2.2: if body includes conversation_id, validate it matches the path param.
    # Path value always wins; log a warning on mismatch so operators can detect drift.
    if body.conversation_id is not None and body.conversation_id != conversation_id:
        logger.warning(
            "conversation_id_mismatch_end",
            path_conversation_id=conversation_id,
            body_conversation_id=body.conversation_id,
        )

    async with db_session() as db:
        # Primary: resolve by ElevenLabs conversation ID (spec: CAP-2a)
        cs_lookup = await get_session_by_elevenlabs_id(db, conversation_id)
        resolved_session_id = cs_lookup.id if cs_lookup else conversation_id

        try:
            cs, was_already_closed = await close_session(
                db,
                session_id=resolved_session_id,
                closed_reason=body.reason,
                update_lead_counters=True,
                reconcile_client_id=body.client_id,
                reconcile_lead_id=body.lead_id,
            )
        except ValueError:
            # Session never existed (and reconciliation also failed or was not attempted).
            # Log at warning level so operators can detect integration failures
            # (e.g. ElevenLabs custom-LLM not firing → no CallSession was ever created).
            # The frontend handles this 404 benignly on WebSocket close paths.
            logger.warning(
                "end_session_unknown_id",
                conversation_id=conversation_id,
                reason=body.reason,
            )
            raise HTTPException(status_code=404, detail="Call session not found")

        if was_already_closed:
            logger.info(
                "end_session_idempotent",
                conversation_id=conversation_id,
                session_id=cs.id,
                reason=body.reason,
            )
        else:
            logger.info(
                "end_session_completed",
                conversation_id=conversation_id,
                session_id=cs.id,
                reason=body.reason,
                duration_seconds=cs.duration_seconds,
            )

    return EndSessionResponse(
        id=cs.id,
        status=cs.status,
        duration_seconds=cs.duration_seconds,
        closed_reason=cs.closed_reason,
    )


# ---------------------------------------------------------------------------
# Read-only inspection endpoints
# ---------------------------------------------------------------------------


@router.get("/{session_id}", dependencies=[Depends(require_api_key)])
async def get_call_session(session_id: str):
    """Get a call session by ID — for admin/debug use."""
    async with db_session() as session:
        cs = await get_session(session, session_id)
        if cs is None:
            raise HTTPException(status_code=404, detail="Call session not found")

        result = _session_to_dict(cs)
        result["elevenlabs_conversation_id"] = cs.elevenlabs_conversation_id
        return result


@router.get("/{session_id}/transcript", response_model=SessionTranscriptResponse, dependencies=[Depends(require_api_key)])
async def get_call_transcript(session_id: str):
    """Get all transcript turns for a call session — for admin/debug use."""
    async with db_session() as session:
        cs = await get_session(session, session_id)
        if cs is None:
            raise HTTPException(status_code=404, detail="Call session not found")

        turns = await get_transcript(session, session_id)
        return SessionTranscriptResponse(
            session_id=session_id,
            turn_count=len(turns),
            turns=[
                TranscriptTurnResponse(
                    id=t.id,
                    role=t.role,
                    content=t.content,
                    timestamp=t.timestamp,
                    filler_detected=bool(t.filler_detected),
                )
                for t in turns
            ],
        )


# ---------------------------------------------------------------------------
# Helpers — JSON text column parsing
# ---------------------------------------------------------------------------


def _parse_json_col(value: str | None, default: Any = None) -> Any:
    """Parse a JSON text column into a Python object.

    Returns default (None) if value is None or empty string.
    Returns default on parse error to avoid crashing on legacy data.
    """
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


@router.get("/{session_id}/analysis", response_model=CallAnalysisResponse, dependencies=[Depends(require_api_key)])
async def get_call_analysis_endpoint(session_id: str):
    """Get the full analysis for a call session (all 12 dimensions).

    Returns 404 if:
    - The call session does not exist.
    - No analysis record exists for the session.

    JSON text columns (objections, products, etc.) are returned as parsed
    Python lists/dicts, not raw JSON strings.
    """
    async with db_session() as session:
        cs = await get_session(session, session_id)
        if cs is None:
            raise HTTPException(status_code=404, detail="Call session not found")

        analysis = await get_call_analysis(session, session_id)
        if analysis is None:
            raise HTTPException(
                status_code=404, detail="No analysis available for this call session"
            )

        return CallAnalysisResponse(
            session_id=analysis.session_id,
            summary=analysis.summary,
            interest_level=analysis.interest_level,
            classification=analysis.classification,
            outcome_reason=analysis.outcome_reason,
            urgency=analysis.urgency,
            primary_need=analysis.primary_need,
            next_action_suggested=analysis.next_action_suggested,
            current_insurance=analysis.current_insurance,
            objections=_parse_json_col(analysis.objections),
            products=_parse_json_col(analysis.products),
            pain_points=_parse_json_col(analysis.pain_points),
            service_issues=_parse_json_col(analysis.service_issues),
            profile_facts=_parse_json_col(analysis.profile_facts),
            commitment_signals=_parse_json_col(analysis.commitment_signals),
            specific_needs=_parse_json_col(analysis.specific_needs),
            misc_notes=_parse_json_col(analysis.misc_notes),
            data_corrections=_parse_json_col(analysis.data_corrections),
            extra_axes_data=_parse_json_col(analysis.extra_axes_data),
            was_abrupt=analysis.was_abrupt,
            abandonment_trigger=analysis.abandonment_trigger,
            analysis_status=analysis.analysis_status,
            analysis_error=analysis.analysis_error,
            analyzed_at=analysis.analyzed_at,
        )
