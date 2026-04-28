"""QORA n8n — Internal API router for n8n ↔ backend communication.

Endpoints (all under /api/v1/internal/):
- GET  /transcript/{session_id}          — fetch formatted transcript as plain text
- GET  /extraction-config/{client_id}    — fetch extraction config (prompt + schema)
- POST /analysis-result                  — receive n8n analysis result and persist it
- GET  /analysis-status/{session_id}     — query local analysis status for a session

All endpoints require X-Internal-Secret header (spec: INTERNAL_API_SECRET).
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.n8n.dependencies import verify_internal_secret
from app.n8n.schemas import N8nCallbackPayload

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/internal",
    tags=["n8n-internal"],
    dependencies=[Depends(verify_internal_secret)],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_db_session() -> AsyncSession:
    """Yield a database session. Used as a FastAPI dependency."""
    from app.core.database import get_session

    async with get_session() as session:
        yield session


# ---------------------------------------------------------------------------
# GET /transcript/{session_id}
# ---------------------------------------------------------------------------


@router.get("/transcript/{session_id}", response_class=PlainTextResponse)
async def get_transcript(session_id: str) -> PlainTextResponse:
    """Return the formatted call transcript as plain text for n8n analysis.

    Args:
        session_id: UUID of the call session.

    Returns:
        Plain text with one "role: content" line per transcript turn.

    Raises:
        HTTPException 404: If session does not exist or has no transcript turns.
    """
    from app.core.database import get_session
    from app.calls.models import TranscriptTurn

    async with get_session() as db:
        result = await db.execute(
            select(TranscriptTurn)
            .where(TranscriptTurn.session_id == session_id)
            .order_by(TranscriptTurn.timestamp)
        )
        turns = list(result.scalars().all())

    if not turns:
        raise HTTPException(
            status_code=404,
            detail=f"No transcript found for session_id={session_id!r}",
        )

    # Format: "role: content" per line (same as summarizer._format_transcript)
    lines = []
    for turn in turns:
        role_label = "Agente" if turn.role == "agent" else "Lead"
        lines.append(f"{role_label}: {turn.content}")
    transcript_text = "\n".join(lines)

    return PlainTextResponse(content=transcript_text)


# ---------------------------------------------------------------------------
# GET /extraction-config/{client_id}
# ---------------------------------------------------------------------------


@router.get("/extraction-config/{client_id}")
async def get_extraction_config(client_id: str) -> dict[str, Any]:
    """Return the extraction config (system prompt + response schema) for n8n.

    Returns 404 when the client does not exist OR the client has no
    extraction_config configured (per spec requirement).

    Args:
        client_id: UUID of the client.

    Returns:
        JSON with client_id, system_prompt, and response_schema dict.

    Raises:
        HTTPException 404: If client does not exist or has no extraction config.
    """
    from app.core.database import get_session
    from app.tenants.models import Client
    from app.analysis_schema import (
        ExtractionConfig,
        build_system_prompt,
        build_analysis_model,
    )

    async with get_session() as db:
        result = await db.execute(select(Client).where(Client.id == client_id))
        client = result.scalar_one_or_none()

    if client is None:
        raise HTTPException(
            status_code=404,
            detail=f"Client not found: client_id={client_id!r}",
        )

    # Load ExtractionConfig — 404 if not configured (spec requirement)
    extraction_cfg: ExtractionConfig | None = None
    if client.extraction_config:
        try:
            config_dict = json.loads(client.extraction_config)
            extraction_cfg = ExtractionConfig.model_validate(config_dict)
        except Exception as exc:
            logger.warning(
                "n8n_config_invalid_extraction_config",
                client_id=client_id,
                error=str(exc),
            )

    if extraction_cfg is None:
        raise HTTPException(
            status_code=404,
            detail=f"No extraction config found for client_id={client_id!r}",
        )

    system_prompt = build_system_prompt(extraction_cfg)

    # Build response schema from the dynamic model's JSON schema
    response_schema: dict[str, Any] = {}
    try:
        model = build_analysis_model(extraction_cfg)
        response_schema = model.model_json_schema()
    except Exception as exc:
        logger.warning(
            "n8n_config_schema_build_failed",
            client_id=client_id,
            error=str(exc),
        )

    return {
        "client_id": client_id,
        "system_prompt": system_prompt,
        "response_schema": response_schema,
    }


# ---------------------------------------------------------------------------
# POST /analysis-result
# ---------------------------------------------------------------------------


@router.post("/analysis-result")
async def analysis_callback(payload: N8nCallbackPayload) -> dict[str, str]:
    """Receive n8n analysis result and persist it.

    Spec contract: accepts {session_id, summary, facts}.
    Persists CallAnalysis record and triggers verification comparison log.

    Args:
        payload: N8nCallbackPayload with session_id (required), summary, facts.

    Returns:
        {"status": "accepted"} on success.
    """
    from app.core.database import get_session
    from app.calls.models import CallSession
    from app.n8n.verification import log_verification_comparison

    logger.info(
        "n8n_callback_received",
        session_id=payload.session_id,
        n8n_execution_id=payload.n8n_execution_id,
        has_summary=payload.summary is not None,
        has_facts=payload.facts is not None,
    )

    # Persist via summarizer helpers when summary and facts are provided
    if payload.summary is not None and payload.facts is not None:
        async with get_session() as db:
            # Load session to get lead_id and client_id
            cs_result = await db.execute(
                select(CallSession).where(CallSession.id == payload.session_id)
            )
            cs = cs_result.scalar_one_or_none()

            if cs is not None:
                try:
                    async with db.begin_nested():
                        from app.summarizer import _upsert_call_analysis

                        await _upsert_call_analysis(
                            db,
                            payload.session_id,
                            cs.lead_id,
                            cs.client_id,
                            payload.summary,
                            payload.facts,
                        )
                    # Log the verification comparison
                    await log_verification_comparison(
                        session_id=payload.session_id,
                        n8n_summary=payload.summary,
                        n8n_facts=payload.facts,
                        db=db,
                    )
                except Exception as exc:
                    logger.error(
                        "n8n_callback_persist_failed",
                        session_id=payload.session_id,
                        error=str(exc),
                    )
            else:
                logger.warning(
                    "n8n_callback_session_not_found",
                    session_id=payload.session_id,
                )
    else:
        logger.info(
            "n8n_callback_no_results",
            session_id=payload.session_id,
            reason="summary or facts not provided",
        )

    return {"status": "accepted"}


# ---------------------------------------------------------------------------
# GET /analysis-status/{session_id}
# ---------------------------------------------------------------------------


@router.get("/analysis-status/{session_id}")
async def get_analysis_status(session_id: str) -> dict[str, Any]:
    """Return the local analysis status for a session.

    Args:
        session_id: UUID of the call session.

    Returns:
        JSON with session_id, local_status (from CallAnalysis), and n8n_status (None).

    Raises:
        HTTPException 404: If no CallSession exists for the given session_id.
    """
    from app.core.database import get_session
    from app.calls.models import CallSession, CallAnalysis

    async with get_session() as db:
        cs_result = await db.execute(
            select(CallSession).where(CallSession.id == session_id)
        )
        cs = cs_result.scalar_one_or_none()

        if cs is None:
            raise HTTPException(
                status_code=404,
                detail=f"Session not found: session_id={session_id!r}",
            )

        # Check for analysis record
        ca_result = await db.execute(
            select(CallAnalysis).where(CallAnalysis.session_id == session_id)
        )
        ca = ca_result.scalar_one_or_none()

    local_status = ca.analysis_status if ca is not None else "pending"

    return {
        "session_id": session_id,
        "local_status": local_status,
        "n8n_status": None,  # Phase 1 — n8n status tracking is future work
    }
