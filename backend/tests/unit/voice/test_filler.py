"""Unit tests for filler state — dedup, last-filler tracking, fallback selection.

RED: References app.voice.filler which is not yet implemented.
Covers: CAP-5 scenarios.

Updated (T27): SessionStore now uses composite (client_id, conversation_id) key
to prevent cross-tenant state leakage when two tenants share the same conversation_id.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# T3.2: Filler state tests
# ---------------------------------------------------------------------------


def test_create_conversation_state():
    """ConversationState can be created with required fields."""
    from app.voice.filler import ConversationState

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
    assert state.last_filler is None
    assert state.turn_count == 0


def test_session_store_create_and_get():
    """SessionStore.create() and get() work correctly with composite key."""
    from app.voice.filler import SessionStore

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
    from app.voice.filler import SessionStore

    store = SessionStore()
    assert store.get(("quintana-seguros", "nonexistent")) is None


def test_session_store_get_with_string_returns_none():
    """SessionStore.get() returns None when called with a bare string (old API guard)."""
    from app.voice.filler import SessionStore

    store = SessionStore()
    store.create("conv-001", "quintana-seguros", "lead-001", "session-001")
    # Old string-based lookup must return None — guards against accidental old usage
    assert store.get("conv-001") is None


def test_session_store_two_tenants_same_conversation_id_isolated():
    """Two tenants with the same conversation_id have independent entries."""
    from app.voice.filler import SessionStore

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


def test_update_filler_tracks_last_filler():
    """update_filler() sets last_filler on the state."""
    from app.voice.filler import SessionStore

    store = SessionStore()
    store.create("conv-001", "quintana-seguros", "lead-001", "session-001")

    store.update_filler("quintana-seguros", "conv-001", "A ver...")

    state = store.get(("quintana-seguros", "conv-001"))
    assert state.last_filler == "A ver..."


def test_filler_dedup_no_consecutive_repeat():
    """select_filler() never repeats the same filler consecutively."""
    from app.voice.filler import select_filler, SessionStore

    store = SessionStore()
    store.create("conv-001", "quintana-seguros", "lead-001", "session-001")

    # Use the first filler and update state
    filler1 = select_filler(store.get(("quintana-seguros", "conv-001")))
    store.update_filler("quintana-seguros", "conv-001", filler1)

    # Get second filler — must be different
    filler2 = select_filler(store.get(("quintana-seguros", "conv-001")))
    assert (
        filler2 != filler1
    ), f"select_filler() returned the same filler twice: {filler1!r}"


def test_filler_dedup_across_multiple_turns():
    """select_filler() never returns the same filler as the previous turn."""
    from app.voice.filler import select_filler, SessionStore

    store = SessionStore()
    store.create("conv-002", "quintana-seguros", "lead-002", "session-002")

    last = None
    for _ in range(10):
        state = store.get(("quintana-seguros", "conv-002"))
        filler = select_filler(state)
        if last is not None:
            assert filler != last, f"Consecutive repeat: {last!r} → {filler!r}"
        store.update_filler("quintana-seguros", "conv-002", filler)
        last = filler


def test_increment_turn_count():
    """increment_turn() increases turn_count on the state."""
    from app.voice.filler import SessionStore

    store = SessionStore()
    store.create("conv-001", "quintana-seguros", "lead-001", "session-001")

    store.increment_turn("quintana-seguros", "conv-001")
    store.increment_turn("quintana-seguros", "conv-001")

    state = store.get(("quintana-seguros", "conv-001"))
    assert state.turn_count == 2


def test_remove_session():
    """remove() deletes a session from the store."""
    from app.voice.filler import SessionStore

    store = SessionStore()
    store.create("conv-001", "quintana-seguros", "lead-001", "session-001")

    store.remove("quintana-seguros", "conv-001")
    assert store.get(("quintana-seguros", "conv-001")) is None


def test_session_count():
    """session_count() returns number of active sessions."""
    from app.voice.filler import SessionStore

    store = SessionStore()
    assert store.session_count() == 0

    store.create("conv-001", "quintana-seguros", "lead-001", "session-001")
    store.create("conv-002", "quintana-seguros", "lead-002", "session-002")
    assert store.session_count() == 2

    store.remove("quintana-seguros", "conv-001")
    assert store.session_count() == 1


def test_fallback_filler_is_safe_phrase():
    """FALLBACK_FILLER is a valid, safe phrase."""
    from app.voice.filler import FALLBACK_FILLER

    assert isinstance(FALLBACK_FILLER, str)
    assert len(FALLBACK_FILLER) > 0
    # Should be a safe, neutral phrase
    assert FALLBACK_FILLER not in ("", " ")


def test_select_filler_returns_string():
    """select_filler() always returns a non-empty string."""
    from app.voice.filler import select_filler, SessionStore

    store = SessionStore()
    state = store.create("conv-001", "quintana-seguros", "lead-001", "session-001")

    filler = select_filler(state)
    assert isinstance(filler, str)
    assert len(filler) > 0
