"""Unit tests for conversation session state — SessionStore create/get/remove/cleanup/count.

Updated: SessionStore now lives in app.voice.session (filler.py renamed to session.py).
SessionStore uses composite (client_id, conversation_id) key to prevent cross-tenant
state leakage when two tenants share the same conversation_id.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# T3.2: ConversationState tests
# ---------------------------------------------------------------------------


def test_create_conversation_state():
    """ConversationState can be created with required fields."""
    from app.voice.session import ConversationState

    state = ConversationState(
        conversation_id="conv-001",
        client_id="quintana-seguros",
        lead_id="lead-001",
        session_id="session-001",
    )
    assert state.conversation_id == "conv-001"
    assert state.client_id == "quintana-seguros"
    assert state.lead_id == "lead-001"
    assert state.session_id == "session-001"
    assert state.turn_count == 0


def test_session_store_create_and_get():
    """SessionStore.create() and get() work correctly with composite key."""
    from app.voice.session import SessionStore

    store = SessionStore()
    state = store.create(
        conversation_id="conv-001",
        client_id="quintana-seguros",
        lead_id="lead-001",
        session_id="session-001",
    )
    assert state.conversation_id == "conv-001"

    retrieved = store.get(("quintana-seguros", "conv-001"))
    assert retrieved is not None
    assert retrieved.conversation_id == "conv-001"
    assert retrieved.client_id == "quintana-seguros"


def test_session_store_get_missing_returns_none():
    """SessionStore.get() returns None for unknown conversation."""
    from app.voice.session import SessionStore

    store = SessionStore()
    assert store.get(("quintana-seguros", "nonexistent")) is None


def test_session_store_get_with_string_returns_none():
    """SessionStore.get() returns None when called with a bare string (old API guard)."""
    from app.voice.session import SessionStore

    store = SessionStore()
    store.create("conv-001", "quintana-seguros", "lead-001", "session-001")
    # Old string-based lookup must return None — guards against accidental old usage
    assert store.get("conv-001") is None


def test_session_store_two_tenants_same_conversation_id_isolated():
    """Two tenants with the same conversation_id have independent entries."""
    from app.voice.session import SessionStore

    store = SessionStore()
    store.create("conv-shared", "tenant-a", "lead-001", "session-a")
    store.create("conv-shared", "tenant-b", "lead-002", "session-b")

    state_a = store.get(("tenant-a", "conv-shared"))
    state_b = store.get(("tenant-b", "conv-shared"))

    assert state_a is not None
    assert state_b is not None
    assert state_a.client_id == "tenant-a"
    assert state_b.client_id == "tenant-b"
    # Both entries coexist independently
    assert store.session_count() == 2


def test_increment_turn_count():
    """increment_turn() increases turn_count on the state."""
    from app.voice.session import SessionStore

    store = SessionStore()
    store.create("conv-001", "quintana-seguros", "lead-001", "session-001")

    store.increment_turn("quintana-seguros", "conv-001")
    store.increment_turn("quintana-seguros", "conv-001")

    state = store.get(("quintana-seguros", "conv-001"))
    assert state.turn_count == 2


def test_remove_session():
    """remove() deletes a session from the store."""
    from app.voice.session import SessionStore

    store = SessionStore()
    store.create("conv-001", "quintana-seguros", "lead-001", "session-001")

    store.remove("quintana-seguros", "conv-001")
    assert store.get(("quintana-seguros", "conv-001")) is None


def test_session_count():
    """session_count() returns number of active sessions."""
    from app.voice.session import SessionStore

    store = SessionStore()
    assert store.session_count() == 0

    store.create("conv-001", "quintana-seguros", "lead-001", "session-001")
    store.create("conv-002", "quintana-seguros", "lead-002", "session-002")
    assert store.session_count() == 2

    store.remove("quintana-seguros", "conv-001")
    assert store.session_count() == 1


def test_cleanup_expired():
    """cleanup_expired() removes sessions older than ttl_seconds."""
    import time
    from app.voice.session import SessionStore

    store = SessionStore()
    state = store.create("conv-old", "quintana-seguros", "lead-001", "session-001")
    # Manually set started_at to way in the past
    state.started_at = time.monotonic() - 400  # 400 seconds ago

    removed = store.cleanup_expired(ttl_seconds=300)
    assert removed == 1
    assert store.get(("quintana-seguros", "conv-old")) is None
