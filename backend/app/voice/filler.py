"""QORA Voice — In-memory conversation state and filler dedup logic.

Implements AD-3: In-Memory Session Store for filler tracking.
Covers: CAP-5 filler repetition prevention and 500ms fallback.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Filler pools (CAP-5: contextual + varied)
# ---------------------------------------------------------------------------

# Grouped by conversational context
FILLER_POOLS: list[list[str]] = [
    # Thinking / searching
    [
        "A ver...",
        "Mmm, dejame ver...",
        "Estoy chequeando...",
        "Hmm, un momento...",
    ],
    # Processing / computing
    [
        "Dale, ya lo estoy mirando...",
        "Un segundo...",
        "Dejame revisar eso...",
        "Voy a verificar...",
    ],
    # Transitioning
    [
        "Bueno, entonces...",
        "Perfecto, y ahí...",
        "Claro, y con respecto a eso...",
        "Mirá, te cuento...",
    ],
]

# Flat list of all fillers for dedup selection
_ALL_FILLERS: list[str] = [f for pool in FILLER_POOLS for f in pool]

# Fallback filler for the 500ms timer — safe, context-neutral
FALLBACK_FILLER: str = "Mmm, dejame ver..."


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

    last_filler: str | None = None  # for dedup — never repeat consecutively
    turn_count: int = 0
    started_at: float = field(default_factory=time.monotonic)


# ---------------------------------------------------------------------------
# Filler selection helper
# ---------------------------------------------------------------------------


def select_filler(state: ConversationState) -> str:
    """Select a filler that is NOT the same as the last one used.

    Avoids consecutive repetition per CAP-5 requirement.

    Args:
        state: Current conversation state with last_filler recorded.

    Returns:
        A filler string guaranteed to differ from state.last_filler.
    """
    candidates = [f for f in _ALL_FILLERS if f != state.last_filler]
    if not candidates:
        # Fallback: use any filler (shouldn't happen with multiple fillers)
        candidates = _ALL_FILLERS

    return random.choice(candidates)


# ---------------------------------------------------------------------------
# SessionStore — module-level singleton per process
# ---------------------------------------------------------------------------


class SessionStore:
    """In-memory store for active conversation states.

    Keyed by (client_id, conversation_id) tuple to prevent cross-tenant
    state leakage when two tenants share the same conversation_id value.

    Thread-safety: single-threaded async context (FastAPI); no locks needed.
    Crash resilience: filler tracking only; call data persisted to SQLite.
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

    def update_filler(
        self, client_id: str, conversation_id: str, filler_text: str
    ) -> None:
        """Record the last filler used for dedup on next turn.

        Args:
            client_id: Tenant identifier (part of composite key).
            conversation_id: ElevenLabs conversation ID.
            filler_text: The filler phrase just emitted.
        """
        state = self._sessions.get((client_id, conversation_id))
        if state is not None:
            state.last_filler = filler_text

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
