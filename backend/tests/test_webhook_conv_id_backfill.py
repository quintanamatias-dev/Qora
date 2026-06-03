"""Tests for backend-only conversation_id backfill at webhook time.

Spec: Domain 1 — Backend-Only Conversation ID Resolution
Tasks 2.1, 2.2, and 2.1b.

Problem 1 fix: when find_by_client_lead returns an initiation-cached entry with a
real EL conversation_id (non-demo-*), that ID must be promoted to
persisted_conversation_id so the CallSession is stored with it — not NULL.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers shared by 2.1, 2.2, and 2.1b production-path tests
# ---------------------------------------------------------------------------


def _make_patch_context(mock_create_session, mock_db):
    """Return a context manager stack that patches webhook internals for unit testing."""

    @asynccontextmanager
    async def _mock_db_session_ctx():
        yield mock_db

    def _db_session_factory():
        return _mock_db_session_ctx()

    return (
        patch("app.voice.webhook.create_session", side_effect=mock_create_session),
        patch("app.voice.webhook.get_client", return_value=MagicMock(
            is_active=True, tools_enabled=None, system_prompt_override="Test prompt",
            model="gpt-4o", temperature=0.7, max_tokens=300,
        )),
        patch("app.voice.webhook.get_default_agent", return_value=None),
        patch("app.voice.webhook.get_lead", return_value=None),
        patch("app.voice.webhook.db_session", side_effect=_db_session_factory),
        patch("app.voice.webhook._stream_llm_response", return_value=_noop_gen()),
    )


# ---------------------------------------------------------------------------
# Task 2.1 — real EL conv_id IS written to DB via create_session
# Tests the PRODUCTION CODE PATH; does not reproduce the branch condition locally.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_promotes_real_conv_id_to_db_session(test_settings, db_engine):
    """When session_store has a real (non-demo-*) conv_id, create_session receives it.

    GIVEN session_store has an entry with conversation_id='EL-REAL-2point1-conv' and session_id=''
    AND the webhook receives NO conversation_id in the request body
    WHEN _process_custom_llm_request runs (PRODUCTION code path)
    THEN create_session IS called with elevenlabs_conversation_id = 'EL-REAL-2point1-conv'
    (not None, not a demo-* prefix — the real ID is written to DB).

    Outcome assertion: tests what got PERSISTED, not which if-branch ran.
    """
    from app.voice.session import session_store
    from app.voice.webhook import CustomLLMRequest, ElevenLabsExtraBody, _process_custom_llm_request

    real_el_conv_id = "EL-REAL-2point1-conv"
    lead_id = "lead-2point1-real"
    client_id = "quintana-seguros"

    session_store.create(
        conversation_id=real_el_conv_id,
        client_id=client_id,
        lead_id=lead_id,
        session_id="",
    )

    body = CustomLLMRequest(
        messages=[{"role": "user", "content": "hola"}],
        elevenlabs_extra_body=ElevenLabsExtraBody(
            lead_id=lead_id,
            conversation_id=None,  # EL sent no conversation_id
        ),
    )
    request = MagicMock()
    request.app.state.settings = test_settings

    created_calls = []

    async def _mock_create_session(db, *, client_id, lead_id, elevenlabs_conversation_id, agent_id=None):
        created_calls.append({"elevenlabs_conversation_id": elevenlabs_conversation_id})
        sess = MagicMock()
        sess.id = "sess-2point1"
        return sess

    mock_db = AsyncMock()
    patches = _make_patch_context(_mock_create_session, mock_db)

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        await _process_custom_llm_request(body=body, client_id=client_id, request=request)

    # OUTCOME: create_session must have been called with the real EL conv_id
    assert len(created_calls) == 1, (
        f"create_session must be called exactly once; got {len(created_calls)} calls"
    )
    assert created_calls[0]["elevenlabs_conversation_id"] == real_el_conv_id, (
        f"create_session must receive elevenlabs_conversation_id={real_el_conv_id!r}; "
        f"got {created_calls[0]['elevenlabs_conversation_id']!r}"
    )


# ---------------------------------------------------------------------------
# Task 2.2 — demo-* conv_id is NOT written to DB (persisted as NULL)
# Tests the PRODUCTION CODE PATH; does not reproduce the branch condition locally.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_does_not_persist_demo_conv_id_to_db(test_settings, db_engine):
    """When session_store has a demo-* conv_id, create_session receives None (stored as NULL).

    GIVEN session_store has an entry with conversation_id='demo-fallback-xyz' and session_id=''
    AND the webhook receives NO conversation_id in the request body
    WHEN _process_custom_llm_request runs (PRODUCTION code path)
    THEN create_session IS called with elevenlabs_conversation_id = None
    (demo-* IDs must NOT be written to the DB column — they are internal fallbacks only).

    Outcome assertion: tests what got PERSISTED (NULL), not which if-branch ran.
    """
    from app.voice.session import session_store
    from app.voice.webhook import CustomLLMRequest, ElevenLabsExtraBody, _process_custom_llm_request

    demo_conv_id = "demo-fallback-xyz"
    lead_id = "lead-2point2-demo"
    client_id = "quintana-seguros"

    session_store.create(
        conversation_id=demo_conv_id,
        client_id=client_id,
        lead_id=lead_id,
        session_id="",
    )

    body = CustomLLMRequest(
        messages=[{"role": "user", "content": "hola"}],
        elevenlabs_extra_body=ElevenLabsExtraBody(
            lead_id=lead_id,
            conversation_id=None,  # EL sent no conversation_id
        ),
    )
    request = MagicMock()
    request.app.state.settings = test_settings

    created_calls = []

    async def _mock_create_session(db, *, client_id, lead_id, elevenlabs_conversation_id, agent_id=None):
        created_calls.append({"elevenlabs_conversation_id": elevenlabs_conversation_id})
        sess = MagicMock()
        sess.id = "sess-2point2"
        return sess

    mock_db = AsyncMock()
    patches = _make_patch_context(_mock_create_session, mock_db)

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        await _process_custom_llm_request(body=body, client_id=client_id, request=request)

    # OUTCOME: create_session must have been called with None (demo-* suppressed)
    assert len(created_calls) == 1, (
        f"create_session must be called exactly once; got {len(created_calls)} calls"
    )
    assert created_calls[0]["elevenlabs_conversation_id"] is None, (
        "demo-* conv_id must NOT be promoted — create_session must receive "
        f"elevenlabs_conversation_id=None, got {created_calls[0]['elevenlabs_conversation_id']!r}"
    )


# ---------------------------------------------------------------------------
# Task 2.1b — production path: webhook creates DB session with real conv_id
# when conv_state exists but session_id is empty (initiation-cached without DB write)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_backfill_creates_db_session_when_conv_state_has_no_session_id(
    test_settings, db_engine
):
    """_process_custom_llm_request calls create_session with the real EL conv_id when
    conv_state exists (from initiation) but has session_id="" (no DB record yet).

    GIVEN session_store has entry with conversation_id='EL-REAL-abc456def', session_id=''
    AND the webhook receives NO conversation_id in the request body
    WHEN _process_custom_llm_request runs
    THEN create_session IS called (UNCONDITIONALLY, not behind an if-guard)
    AND it is called with elevenlabs_conversation_id = 'EL-REAL-abc456def'
    AND the conv_state.session_id is updated with the new DB session id.

    This tests the PRODUCTION CODE PATH in webhook.py, not copied branch logic.
    """
    from app.voice.session import session_store

    real_el_conv_id = "EL-REAL-abc456def"
    lead_id = "lead-backfill-prod-path"
    client_id = "quintana-seguros"

    # Pre-populate the store exactly as the initiation webhook does:
    # real EL conv_id present, session_id="" because DB create_session was not called yet.
    session_store.create(
        conversation_id=real_el_conv_id,
        client_id=client_id,
        lead_id=lead_id,
        session_id="",  # initiation did NOT call create_session
    )
    assert session_store.find_by_client_lead(client_id, lead_id) is not None

    from app.voice.webhook import CustomLLMRequest, ElevenLabsExtraBody, _process_custom_llm_request

    body = CustomLLMRequest(
        messages=[{"role": "user", "content": "hola"}],
        elevenlabs_extra_body=ElevenLabsExtraBody(
            lead_id=lead_id,
            conversation_id=None,  # EL did NOT send a conversation_id in this turn
        ),
    )

    request = MagicMock()
    request.app.state.settings = test_settings

    created_session_calls = []

    async def _mock_create_session(db, *, client_id, lead_id, elevenlabs_conversation_id, agent_id=None):
        created_session_calls.append({
            "client_id": client_id,
            "lead_id": lead_id,
            "elevenlabs_conversation_id": elevenlabs_conversation_id,
        })
        mock_sess = MagicMock()
        mock_sess.id = "backfill-new-session-id"
        return mock_sess

    mock_db = AsyncMock()

    @asynccontextmanager
    async def _mock_db_session_ctx():
        yield mock_db

    def _db_session_factory():
        return _mock_db_session_ctx()

    with (
        patch("app.voice.webhook.create_session", side_effect=_mock_create_session),
        patch("app.voice.webhook.get_client", return_value=MagicMock(
            is_active=True, tools_enabled=None, system_prompt_override="Test prompt",
            model="gpt-4o", temperature=0.7, max_tokens=300,
        )),
        patch("app.voice.webhook.get_default_agent", return_value=None),
        patch("app.voice.webhook.get_lead", return_value=None),
        patch("app.voice.webhook.db_session", side_effect=_db_session_factory),
        patch("app.voice.webhook._stream_llm_response", return_value=_noop_gen()),
    ):
        await _process_custom_llm_request(
            body=body, client_id=client_id, request=request
        )

    # UNCONDITIONAL assertion — create_session MUST have been called exactly once.
    # No `if created_session_calls:` guard — that would let the test pass on a no-op.
    assert len(created_session_calls) == 1, (
        f"create_session must be called exactly once for the backfill path; "
        f"got {len(created_session_calls)} calls. "
        "If 0: the webhook is NOT persisting the promoted conversation_id to DB."
    )

    call = created_session_calls[0]
    assert call["elevenlabs_conversation_id"] == real_el_conv_id, (
        f"create_session must receive elevenlabs_conversation_id={real_el_conv_id!r}; "
        f"got {call['elevenlabs_conversation_id']!r}"
    )

    # Also verify the conv_state was updated with the new session_id
    updated_state = session_store.find_by_client_lead(client_id, lead_id)
    assert updated_state is not None
    assert updated_state.session_id == "backfill-new-session-id", (
        f"conv_state.session_id must be updated to the new DB session id; "
        f"got {updated_state.session_id!r}"
    )


async def _noop_gen():
    """Empty async generator for mocking stream."""
    return
    yield  # make it a generator
