"""Unit tests for filler selection policy — context grouping and repetition prevention.

Tests cover:
- Same filler never repeats consecutively
- Filler varies by context (different pools)
- Fallback filler is available when state has no last_filler
- select_filler returns strings from known pools

Covers: T6.2 (filler-selection tests per spec CAP-5).
"""

from __future__ import annotations

from app.voice.filler import (
    FILLER_POOLS,
    FALLBACK_FILLER,
    ConversationState,
    SessionStore,
    select_filler,
    _ALL_FILLERS,
)


# ---------------------------------------------------------------------------
# Filler pool structure tests
# ---------------------------------------------------------------------------


def test_filler_pools_are_non_empty():
    """FILLER_POOLS contains at least 3 context groups."""
    assert len(FILLER_POOLS) >= 3
    for pool in FILLER_POOLS:
        assert len(pool) >= 2, f"Each pool should have at least 2 fillers, got: {pool}"


def test_all_fillers_contains_entries_from_all_pools():
    """_ALL_FILLERS is the flat union of all filler pools."""
    all_from_pools = [f for pool in FILLER_POOLS for f in pool]
    for filler in all_from_pools:
        assert filler in _ALL_FILLERS


def test_fallback_filler_is_in_all_fillers():
    """FALLBACK_FILLER is a member of the known filler pool."""
    assert FALLBACK_FILLER in _ALL_FILLERS


# ---------------------------------------------------------------------------
# select_filler — repetition prevention
# ---------------------------------------------------------------------------


def make_state(last_filler: str | None = None) -> ConversationState:
    return ConversationState(
        conversation_id="test-conv-123",
        client_id="quintana-seguros",
        lead_id="lead-001",
        session_id="session-001",
        last_filler=last_filler,
    )


def test_select_filler_returns_string():
    """select_filler() returns a non-empty string."""
    state = make_state()
    result = select_filler(state)
    assert isinstance(result, str)
    assert len(result) > 0


def test_select_filler_no_last_filler_returns_any():
    """select_filler() with no last_filler returns any filler."""
    state = make_state(last_filler=None)
    result = select_filler(state)
    assert result in _ALL_FILLERS


def test_select_filler_never_repeats_last():
    """select_filler() never returns the same filler as last_filler."""
    for filler in _ALL_FILLERS:
        state = make_state(last_filler=filler)
        result = select_filler(state)
        assert result != filler, (
            f"select_filler returned the same filler '{filler}' as last_filler"
        )


def test_select_filler_varies_across_calls():
    """Multiple calls to select_filler produce variety (not always the same)."""
    state = make_state(last_filler=None)
    # Run 20 times — should not always return the exact same string
    results = {select_filler(state) for _ in range(20)}
    assert len(results) > 1, "select_filler should produce varied results"


def test_select_filler_result_is_valid_filler():
    """select_filler() always returns a filler from the known pool."""
    state = make_state(last_filler="A ver...")
    for _ in range(10):
        result = select_filler(state)
        assert result in _ALL_FILLERS


# ---------------------------------------------------------------------------
# SessionStore — filler state tracking
# ---------------------------------------------------------------------------


def test_session_store_create_and_get():
    """SessionStore.create() and .get() work correctly."""
    store = SessionStore()
    state = store.create(
        conversation_id="conv-aaa",
        client_id="quintana-seguros",
        lead_id="lead-001",
        session_id="sess-001",
    )
    assert state is not None
    assert store.get("conv-aaa") is state


def test_session_store_update_filler():
    """SessionStore.update_filler() sets last_filler on the state."""
    store = SessionStore()
    store.create(
        conversation_id="conv-bbb",
        client_id="quintana-seguros",
        lead_id="lead-001",
        session_id="sess-001",
    )
    store.update_filler("conv-bbb", "A ver...")
    state = store.get("conv-bbb")
    assert state.last_filler == "A ver..."


def test_session_store_filler_dedup_via_select():
    """After update_filler, subsequent select_filler avoids the recorded filler."""
    store = SessionStore()
    store.create(
        conversation_id="conv-ccc",
        client_id="quintana-seguros",
        lead_id="lead-001",
        session_id="sess-001",
    )
    store.update_filler("conv-ccc", "A ver...")
    state = store.get("conv-ccc")
    result = select_filler(state)
    assert result != "A ver...", "Filler after update must differ from last recorded"


def test_session_store_no_repeat_across_turns():
    """Simulated 5-turn conversation never uses same filler twice in a row."""
    store = SessionStore()
    store.create(
        conversation_id="conv-multi",
        client_id="quintana-seguros",
        lead_id="lead-001",
        session_id="sess-001",
    )

    last_filler = None
    for _ in range(5):
        state = store.get("conv-multi")
        chosen = select_filler(state)
        assert chosen != last_filler, (
            f"Consecutive repeat of filler '{chosen}' detected!"
        )
        store.update_filler("conv-multi", chosen)
        last_filler = chosen


def test_session_store_increment_turn():
    """SessionStore.increment_turn() increments turn_count."""
    store = SessionStore()
    store.create(
        conversation_id="conv-turns",
        client_id="quintana-seguros",
        lead_id="lead-001",
        session_id="sess-001",
    )
    store.increment_turn("conv-turns")
    store.increment_turn("conv-turns")
    state = store.get("conv-turns")
    assert state.turn_count == 2


def test_session_store_remove():
    """SessionStore.remove() deletes the conversation state."""
    store = SessionStore()
    store.create(
        conversation_id="conv-remove",
        client_id="quintana-seguros",
        lead_id="lead-001",
        session_id="sess-001",
    )
    store.remove("conv-remove")
    assert store.get("conv-remove") is None


def test_session_store_cleanup_expired():
    """SessionStore.cleanup_expired() removes old sessions."""
    import time

    store = SessionStore()
    state = store.create(
        conversation_id="conv-old",
        client_id="quintana-seguros",
        lead_id="lead-001",
        session_id="sess-001",
    )
    # Manually set started_at to way in the past
    state.started_at = time.monotonic() - 400  # 400 seconds ago

    removed = store.cleanup_expired(ttl_seconds=300)
    assert removed == 1
    assert store.get("conv-old") is None


def test_filler_context_groups_are_distinct():
    """Each filler pool has distinct members (no cross-pool duplicates)."""
    seen = set()
    for pool in FILLER_POOLS:
        for filler in pool:
            assert filler not in seen, f"Duplicate filler across pools: '{filler}'"
            seen.add(filler)
