"""QORA Calls — Service layer for call session lifecycle and transcript management.

Covers: CAP-7 call session lifecycle, transcript turns, billable minutes.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.calls.models import CallSession, TranscriptTurn


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


async def create_session(
    session: AsyncSession,
    *,
    client_id: str,
    lead_id: str,
    elevenlabs_conversation_id: str | None = None,
    session_id: str | None = None,
) -> CallSession:
    """Create a new call session with status=initiated.

    Args:
        session: Active async DB session.
        client_id: Tenant client id.
        lead_id: Lead being called.
        elevenlabs_conversation_id: Optional ElevenLabs conversation ID.
        session_id: Optional pre-generated UUID (uses uuid4 if not provided).

    Returns:
        Persisted CallSession instance.
    """
    cs = CallSession(
        id=session_id or str(uuid.uuid4()),
        client_id=client_id,
        lead_id=lead_id,
        elevenlabs_conversation_id=elevenlabs_conversation_id,
        status="initiated",
    )
    session.add(cs)
    await session.flush()
    return cs


async def get_session(session: AsyncSession, session_id: str) -> CallSession | None:
    """Fetch a CallSession by its UUID id.

    Returns:
        CallSession instance or None if not found.
    """
    result = await session.execute(
        select(CallSession).where(CallSession.id == session_id)
    )
    return result.scalar_one_or_none()


async def end_session(
    session: AsyncSession,
    *,
    session_id: str,
    outcome: str,
    duration_seconds: float,
) -> CallSession:
    """Finalize a call session with outcome and billing.

    Args:
        session: Active async DB session.
        session_id: UUID of the call session to finalize.
        outcome: One of 'completed', 'abandoned', 'failed'.
        duration_seconds: Total duration of the call in seconds.

    Returns:
        Updated CallSession instance.

    Raises:
        ValueError: If session not found.
    """
    cs = await get_session(session, session_id)
    if cs is None:
        raise ValueError(f"CallSession not found: {session_id!r}")

    cs.ended_at = datetime.now(timezone.utc)
    cs.duration_seconds = duration_seconds
    cs.outcome = outcome
    cs.status = outcome  # status mirrors outcome for completed/abandoned/failed
    cs.billable_minutes = math.ceil(duration_seconds / 60)

    await session.flush()
    return cs


# ---------------------------------------------------------------------------
# Transcript management
# ---------------------------------------------------------------------------


async def add_transcript_turn(
    session: AsyncSession,
    session_id: str,
    role: str,
    content: str,
    filler_detected: bool = False,
) -> TranscriptTurn:
    """Append a transcript turn to a call session.

    Args:
        session: Active async DB session.
        session_id: UUID of the call session.
        role: 'user', 'agent', or 'tool'.
        content: Text content of the turn.
        filler_detected: Whether this turn was a filler injection.

    Returns:
        Persisted TranscriptTurn instance.
    """
    turn = TranscriptTurn(
        id=str(uuid.uuid4()),
        session_id=session_id,
        role=role,
        content=content,
        filler_detected=1 if filler_detected else 0,
    )
    session.add(turn)
    await session.flush()
    return turn


async def get_transcript(
    session: AsyncSession, session_id: str
) -> list[TranscriptTurn]:
    """Return all transcript turns for a call session, ordered by timestamp.

    Args:
        session: Active async DB session.
        session_id: UUID of the call session.

    Returns:
        List of TranscriptTurn instances in chronological order.
    """
    result = await session.execute(
        select(TranscriptTurn)
        .where(TranscriptTurn.session_id == session_id)
        .order_by(TranscriptTurn.timestamp)
    )
    return list(result.scalars().all())
