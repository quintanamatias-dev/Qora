"""QORA Voice — Debug endpoints for inspecting cached VoiceSessionContext.

TEMPORARY tooling for local development verification only.
- No authentication required (local dev only).
- Read-only, no side effects.
- DO NOT expose in production.

Endpoints:
  GET /voice/debug/context                     — All active sessions + context preview
  GET /voice/debug/context/{conversation_id}   — Full context for one session
"""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException

from app.voice.session import session_store

router = APIRouter(prefix="/voice/debug", tags=["debug"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _preview(text: str, max_chars: int = 200) -> str:
    """Return the first max_chars of text, or the full text if shorter."""
    if not text:
        return ""
    return text[:max_chars]


def _context_preview(ctx) -> dict:
    """Serialize a VoiceSessionContext into a preview dict (truncated fields)."""
    return {
        "system_prompt_preview": _preview(ctx.system_prompt),
        "system_prompt_length": len(ctx.system_prompt or ""),
        "skills_index_preview": _preview(ctx.skills_index),
        "skills_index_length": len(ctx.skills_index or ""),
        "misc_notes_preview": _preview(ctx.misc_notes),
        "misc_notes_length": len(ctx.misc_notes or ""),
        "lead_profile_preview": _preview(ctx.lead_profile),
        "lead_profile_length": len(ctx.lead_profile or ""),
        "model": ctx.model,
        "temperature": ctx.temperature,
        "max_tokens": ctx.max_tokens,
    }


def _context_full(ctx) -> dict:
    """Serialize a VoiceSessionContext into a full (un-truncated) dict."""
    return {
        "system_prompt": ctx.system_prompt,
        "skills_index": ctx.skills_index,
        "misc_notes": ctx.misc_notes,
        "lead_profile": ctx.lead_profile,
        "model": ctx.model,
        "temperature": ctx.temperature,
        "max_tokens": ctx.max_tokens,
    }


def _session_summary(state, *, full: bool = False) -> dict:
    """Build a JSON-serializable dict for one ConversationState."""
    has_ctx = state.context is not None
    age_seconds = round(time.monotonic() - state.started_at, 1)

    entry: dict = {
        "conversation_id": state.conversation_id,
        "client_id": state.client_id,
        "lead_id": state.lead_id,
        "session_id": state.session_id,
        "age_seconds": age_seconds,
        "has_context": has_ctx,
        "turn_count": state.turn_count,
    }

    if has_ctx:
        entry["context"] = _context_full(state.context) if full else _context_preview(state.context)

    return entry


# ---------------------------------------------------------------------------
# GET /voice/debug/context — all active sessions (preview)
# ---------------------------------------------------------------------------


@router.get("/context")
async def list_debug_contexts():
    """Return all active conversation sessions with a context preview.

    Iterates over session_store._sessions directly (internal dict).
    Intended for local dev verification only — no auth, read-only.
    """
    sessions = []
    for state in session_store._sessions.values():
        sessions.append(_session_summary(state, full=False))

    return {
        "active_sessions": sessions,
        "total_sessions": len(sessions),
    }


# ---------------------------------------------------------------------------
# GET /voice/debug/context/{conversation_id} — full context for one session
# ---------------------------------------------------------------------------


@router.get("/context/{conversation_id}")
async def get_debug_context(conversation_id: str):
    """Return the full (un-truncated) cached context for a single conversation.

    Searches all tenants for the given conversation_id (since the store is keyed
    by (client_id, conversation_id) and the client_id may be unknown to the caller).

    Raises:
        404: If no active session matches the given conversation_id.
    """
    matches = [
        state
        for (_, conv_id), state in session_store._sessions.items()
        if conv_id == conversation_id
    ]

    if not matches:
        raise HTTPException(
            status_code=404,
            detail=f"No active session found for conversation_id={conversation_id!r}",
        )

    # There should only ever be one match per conversation_id in practice,
    # but return them all just in case two tenants somehow share one.
    sessions = [_session_summary(state, full=True) for state in matches]

    return {
        "conversation_id": conversation_id,
        "sessions": sessions,
        "total_matches": len(sessions),
    }
