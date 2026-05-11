"""Unit tests for ConversationState.context field and SessionStore.create() — VSC-4, VSC-7, VSC-8.

TDD RED phase for Tasks 2.1, 2.2.
Covers spec scenarios:
- Create with context (VSC-4)
- Create without context — backward compat (VSC-4)
- TTL eviction removes sessions with attached context (VSC-7)
- find_by_client_lead: stable session lookup when conversation_id absent (VSC-8)
"""

from __future__ import annotations

import time


def make_voice_context(
    system_prompt: str = "You are Aria.",
    skills_content: str = "",
    misc_notes: str = "",
    lead_profile: str = "",
    model: str = "gpt-4o",
    temperature: float = 0.7,
    max_tokens: int = 300,
    tools: list | None = None,
):
    """Create a VoiceSessionContext instance."""
    from app.voice.context import VoiceSessionContext

    return VoiceSessionContext(
        system_prompt=system_prompt,
        skills_content=skills_content,
        misc_notes=misc_notes,
        lead_profile=lead_profile,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        tools=tools,
    )


# ---------------------------------------------------------------------------
# VSC-4: ConversationState has context field
# ---------------------------------------------------------------------------


def test_conversation_state_has_context_field():
    """ConversationState must have a context field defaulting to None."""
    from app.voice.session import ConversationState

    state = ConversationState(
        conversation_id="conv-001",
        client_id="acme",
        lead_id="lead-001",
        session_id="sess-001",
    )

    assert hasattr(state, "context"), "ConversationState must have 'context' field"
    assert state.context is None, "context must default to None"


def test_conversation_state_context_accepts_voice_context():
    """ConversationState.context accepts a VoiceSessionContext value."""
    from app.voice.session import ConversationState

    ctx = make_voice_context(system_prompt="Test prompt")
    state = ConversationState(
        conversation_id="conv-001",
        client_id="acme",
        lead_id="lead-001",
        session_id="sess-001",
        context=ctx,
    )

    assert state.context is ctx
    assert state.context.system_prompt == "Test prompt"


# ---------------------------------------------------------------------------
# VSC-4: SessionStore.create() accepts optional context
# ---------------------------------------------------------------------------


def test_session_store_create_with_context():
    """VSC-4 create-with-context: session_store.create(..., context=ctx) stores it.

    GIVEN a VoiceSessionContext instance ctx
    WHEN session_store.create(..., context=ctx) is called
    THEN the returned ConversationState.context is ctx
    AND session_store.get((client_id, conversation_id)).context is ctx
    """
    from app.voice.session import SessionStore

    store = SessionStore()
    ctx = make_voice_context(system_prompt="Cached prompt")

    state = store.create(
        conversation_id="conv-001",
        client_id="acme",
        lead_id="lead-001",
        session_id="sess-001",
        context=ctx,
    )

    assert state.context is ctx, "create() must attach context to the returned state"

    # Retrieve and verify context is preserved
    retrieved = store.get(("acme", "conv-001"))
    assert retrieved is not None
    assert retrieved.context is ctx, "context must be retrievable via get()"
    assert retrieved.context.system_prompt == "Cached prompt"


def test_session_store_create_without_context_backward_compat():
    """VSC-4 backward compat: create() without context → context is None.

    GIVEN context is omitted from session_store.create()
    WHEN the call completes
    THEN ConversationState.context is None
    """
    from app.voice.session import SessionStore

    store = SessionStore()

    state = store.create(
        conversation_id="conv-002",
        client_id="acme",
        lead_id="lead-002",
        session_id="sess-002",
    )

    assert state.context is None, "Omitting context must result in context=None"


def test_session_store_create_with_none_context_explicit():
    """Triangulation: explicit context=None also results in context=None."""
    from app.voice.session import SessionStore

    store = SessionStore()

    state = store.create(
        conversation_id="conv-003",
        client_id="acme",
        lead_id=None,
        session_id="sess-003",
        context=None,
    )

    assert state.context is None


# ---------------------------------------------------------------------------
# VSC-7: TTL eviction removes sessions with attached context
# ---------------------------------------------------------------------------


def test_cleanup_expired_removes_session_with_context():
    """VSC-7: Sessions with context are evicted by cleanup_expired() on TTL expiry.

    GIVEN a ConversationState with context set was created > TTL seconds ago
    WHEN session_store.cleanup_expired(ttl_seconds=1) is called
    THEN the session (and its attached context) is removed
    AND session_count() decreases by 1
    """
    from app.voice.session import SessionStore

    store = SessionStore()
    ctx = make_voice_context(system_prompt="Expirable context")

    state = store.create(
        conversation_id="conv-expire",
        client_id="acme",
        lead_id=None,
        session_id="sess-expire",
        context=ctx,
    )

    # Confirm session exists
    assert store.session_count() == 1
    assert state.context is ctx

    # Simulate time passing by manipulating started_at
    state.started_at = time.monotonic() - 10  # 10 seconds ago

    removed = store.cleanup_expired(ttl_seconds=1)

    assert removed == 1, f"Expected 1 session removed, got {removed}"
    assert store.session_count() == 0, "Session must be removed after TTL expiry"
    assert store.get(("acme", "conv-expire")) is None


def test_cleanup_expired_does_not_remove_fresh_session_with_context():
    """Triangulation: Fresh sessions with context are NOT evicted before TTL."""
    from app.voice.session import SessionStore

    store = SessionStore()
    ctx = make_voice_context(system_prompt="Fresh context")

    store.create(
        conversation_id="conv-fresh",
        client_id="acme",
        lead_id=None,
        session_id="sess-fresh",
        context=ctx,
    )

    # Session is brand new, should NOT be evicted
    removed = store.cleanup_expired(ttl_seconds=300)

    assert removed == 0, "Fresh session with context must NOT be evicted"
    assert store.session_count() == 1


# ---------------------------------------------------------------------------
# VSC-8: find_by_client_lead — stable session lookup when conversation_id absent
# ---------------------------------------------------------------------------


def test_find_by_client_lead_returns_existing_session():
    """VSC-8: find_by_client_lead returns the session matching client_id + lead_id.

    GIVEN a session was created for (client_id="acme", lead_id="lead-001")
    WHEN find_by_client_lead("acme", "lead-001") is called
    THEN the matching ConversationState is returned
    """
    from app.voice.session import SessionStore

    store = SessionStore()
    state = store.create(
        conversation_id="conv-stable-001",
        client_id="acme",
        lead_id="lead-001",
        session_id="sess-001",
    )

    found = store.find_by_client_lead("acme", "lead-001")

    assert found is not None, "find_by_client_lead must return the existing session"
    assert found is state, "find_by_client_lead must return the same ConversationState object"
    assert found.conversation_id == "conv-stable-001"


def test_find_by_client_lead_returns_none_when_not_found():
    """VSC-8 triangulation: find_by_client_lead returns None when no session matches.

    GIVEN no session exists for (client_id="acme", lead_id="unknown-lead")
    WHEN find_by_client_lead("acme", "unknown-lead") is called
    THEN None is returned
    """
    from app.voice.session import SessionStore

    store = SessionStore()
    # Create a session for a different lead
    store.create(
        conversation_id="conv-other",
        client_id="acme",
        lead_id="lead-other",
        session_id="sess-other",
    )

    found = store.find_by_client_lead("acme", "unknown-lead")

    assert found is None, "find_by_client_lead must return None when no session matches"


def test_find_by_client_lead_returns_most_recent_when_multiple():
    """VSC-8 triangulation: when multiple sessions exist, returns the one with highest turn count.

    GIVEN two sessions for the same client_id + lead_id with different turn counts
    WHEN find_by_client_lead is called
    THEN the session with the highest turn_count is returned
    """
    import time as time_mod
    from app.voice.session import SessionStore

    store = SessionStore()

    state_old = store.create(
        conversation_id="conv-old",
        client_id="acme",
        lead_id="lead-001",
        session_id="sess-old",
    )
    state_old.turn_count = 2
    state_old.started_at = time_mod.monotonic() - 60  # started 60 seconds ago

    state_new = store.create(
        conversation_id="conv-new",
        client_id="acme",
        lead_id="lead-001",
        session_id="sess-new",
    )
    state_new.turn_count = 5
    state_new.started_at = time_mod.monotonic() - 10  # started 10 seconds ago

    found = store.find_by_client_lead("acme", "lead-001")

    assert found is not None
    assert found is state_new, (
        "find_by_client_lead must return the most recently active session "
        f"(highest turn_count). Got conversation_id={found.conversation_id!r}"
    )


def test_find_by_client_lead_cross_tenant_isolation():
    """VSC-8 security: find_by_client_lead does NOT cross tenant boundaries.

    GIVEN a session exists for client_id="tenant-a" with lead_id="lead-001"
    WHEN find_by_client_lead("tenant-b", "lead-001") is called
    THEN None is returned (different tenant, same lead_id is irrelevant)
    """
    from app.voice.session import SessionStore

    store = SessionStore()
    store.create(
        conversation_id="conv-tenant-a",
        client_id="tenant-a",
        lead_id="lead-001",
        session_id="sess-a",
    )

    found = store.find_by_client_lead("tenant-b", "lead-001")

    assert found is None, (
        "find_by_client_lead must NOT return sessions belonging to a different tenant"
    )
