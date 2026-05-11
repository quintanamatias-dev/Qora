"""QORA Voice — In-memory conversation state and session management.

Implements AD-3: In-Memory Session Store for conversation tracking.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# ConversationState dataclass
# ---------------------------------------------------------------------------


@dataclass
class ConversationState:
    """In-memory state for one ElevenLabs conversation turn.

    Keyed by elevenlabs_conversation_id in the SessionStore.
    """

    conversation_id: str
    client_id: str
    lead_id: str | None = None
    session_id: str = ""  # call_sessions.id in SQLite

    turn_count: int = 0
    started_at: float = field(default_factory=time.monotonic)


# ---------------------------------------------------------------------------
# SessionStore — module-level singleton per process
# ---------------------------------------------------------------------------


class SessionStore:
    """In-memory store for active conversation states.

    Keyed by (client_id, conversation_id) tuple to prevent cross-tenant
    state leakage when two tenants share the same conversation_id value.

    Thread-safety: single-threaded async context (FastAPI); no locks needed.
    Crash resilience: session tracking only; call data persisted to SQLite.
    """

    def __init__(self) -> None:
        self._sessions: dict[tuple[str, str], ConversationState] = {}

    def create(
        self,
        conversation_id: str,
        client_id: str,
        lead_id: str | None,
        session_id: str,
    ) -> ConversationState:
        """Create and store a new ConversationState.

        Args:
            conversation_id: ElevenLabs conversation ID.
            client_id: Tenant client id (part of composite key).
            lead_id: Lead being called.
            session_id: call_sessions.id for DB persistence.

        Returns:
            The newly created ConversationState.
        """
        state = ConversationState(
            conversation_id=conversation_id,
            client_id=client_id,
            lead_id=lead_id,
            session_id=session_id,
        )
        self._sessions[(client_id, conversation_id)] = state
        return state

    def get(self, key: tuple[str, str] | str) -> ConversationState | None:
        """Retrieve a ConversationState by composite key.

        Args:
            key: Composite (client_id, conversation_id) tuple.
                 A bare string is rejected and returns None to prevent
                 accidental use of the old single-key API.

        Returns:
            ConversationState or None if not found.
        """
        if not isinstance(key, tuple):
            return None
        return self._sessions.get(key)

    def increment_turn(self, client_id: str, conversation_id: str) -> None:
        """Increment the turn counter for a conversation.

        Args:
            client_id: Tenant identifier (part of composite key).
            conversation_id: ElevenLabs conversation ID.
        """
        state = self._sessions.get((client_id, conversation_id))
        if state is not None:
            state.turn_count += 1

    def remove(self, client_id: str, conversation_id: str) -> None:
        """Remove a conversation state (call ended).

        Args:
            client_id: Tenant identifier (part of composite key).
            conversation_id: ElevenLabs conversation ID.
        """
        self._sessions.pop((client_id, conversation_id), None)

    def cleanup_expired(self, ttl_seconds: int = 300) -> int:
        """Remove sessions older than ttl_seconds.

        Used by background task to prevent memory leaks.

        Args:
            ttl_seconds: Maximum age in seconds (default 5 minutes).

        Returns:
            Number of sessions removed.
        """
        now = time.monotonic()
        expired = [
            cid
            for cid, state in self._sessions.items()
            if (now - state.started_at) > ttl_seconds
        ]
        for cid in expired:
            del self._sessions[cid]
        return len(expired)

    def session_count(self) -> int:
        """Return number of active sessions in the store."""
        return len(self._sessions)


# ---------------------------------------------------------------------------
# Module-level singleton (T3.5: app uses this directly)
# ---------------------------------------------------------------------------

session_store = SessionStore()
