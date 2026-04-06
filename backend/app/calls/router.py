"""QORA Calls — Admin/debug router for call session inspection.

Provides read-only endpoints for inspecting call sessions and transcripts.
Covers: T3.5 admin/debug router for testing.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.calls.service import get_session, get_transcript
from app.core.database import get_session as db_session

router = APIRouter(prefix="/calls", tags=["calls"])


@router.get("/{session_id}")
async def get_call_session(session_id: str):
    """Get a call session by ID — for admin/debug use."""
    async with db_session() as session:
        cs = await get_session(session, session_id)
        if cs is None:
            raise HTTPException(status_code=404, detail="Call session not found")

        return {
            "id": cs.id,
            "client_id": cs.client_id,
            "lead_id": cs.lead_id,
            "status": cs.status,
            "outcome": cs.outcome,
            "started_at": cs.started_at.isoformat() if cs.started_at else None,
            "ended_at": cs.ended_at.isoformat() if cs.ended_at else None,
            "duration_seconds": cs.duration_seconds,
            "billable_minutes": cs.billable_minutes,
            "elevenlabs_conversation_id": cs.elevenlabs_conversation_id,
        }


@router.get("/{session_id}/transcript")
async def get_call_transcript(session_id: str):
    """Get all transcript turns for a call session — for admin/debug use."""
    async with db_session() as session:
        cs = await get_session(session, session_id)
        if cs is None:
            raise HTTPException(status_code=404, detail="Call session not found")

        turns = await get_transcript(session, session_id)
        return {
            "session_id": session_id,
            "turn_count": len(turns),
            "turns": [
                {
                    "id": t.id,
                    "role": t.role,
                    "content": t.content,
                    "timestamp": t.timestamp.isoformat(),
                    "filler_detected": bool(t.filler_detected),
                }
                for t in turns
            ],
        }
