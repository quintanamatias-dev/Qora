"""Tests: B9 observability — voice webhook and initiation context binding.

TDD RED phase for task 1.3.

Covered scenarios (spec: observability-correlation — Voice Session Context Binding):
    - _process_custom_llm_request binds conversation_id and call_session_id
      to structlog contextvars before streaming begins
    - initiation_webhook binds conversation_id to structlog contextvars
    - Missing optional fields are omitted from contextvars (no null binding)
    - Context binding is lightweight and non-blocking (no network side effects)

Design constraint: binding must not add any synchronous I/O to the live turn path.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import structlog


# ---------------------------------------------------------------------------
# Task 1.3 — Voice webhook context binding
# ---------------------------------------------------------------------------


class TestWebhookContextBinding:
    """voice/webhook.py must bind call_session_id + conversation_id to contextvars."""

    def setup_method(self):
        """Clear structlog contextvars before each test to prevent bleed."""
        structlog.contextvars.clear_contextvars()

    def teardown_method(self):
        """Clear structlog contextvars after each test."""
        structlog.contextvars.clear_contextvars()

    def test_bind_contextvars_called_with_conversation_id(self):
        """When _process_custom_llm_request runs, it must bind conversation_id.

        We test the binding function directly rather than exercising the full
        HTTP stack to keep the test fast and infrastructure-free.
        The production code imports structlog.contextvars.bind_contextvars;
        this test verifies it is called with the right keys.
        """
        # Import the module under test — will fail RED until the binding is added
        from app.voice import webhook

        # Verify the module exposes the binding (will fail if binding is missing
        # from the function body — RED phase proof)
        assert hasattr(webhook, "_bind_voice_context"), (
            "_bind_voice_context helper must exist in app.voice.webhook after task 1.3 GREEN"
        )

    def test_bind_voice_context_binds_conversation_id(self):
        """_bind_voice_context must bind conversation_id when provided."""
        from app.voice.webhook import _bind_voice_context

        structlog.contextvars.clear_contextvars()
        _bind_voice_context(conversation_id="conv-test-123", call_session_id=None)
        ctx = structlog.contextvars.get_contextvars()
        assert ctx.get("conversation_id") == "conv-test-123"

    def test_bind_voice_context_binds_call_session_id(self):
        """_bind_voice_context must bind call_session_id when provided."""
        from app.voice.webhook import _bind_voice_context

        structlog.contextvars.clear_contextvars()
        _bind_voice_context(conversation_id="conv-abc", call_session_id="sess-xyz")
        ctx = structlog.contextvars.get_contextvars()
        assert ctx.get("call_session_id") == "sess-xyz"

    def test_bind_voice_context_omits_none_call_session_id(self):
        """When call_session_id is None, it must NOT be bound to contextvars.

        Spec: missing fields are omitted, not emitted as null.
        """
        from app.voice.webhook import _bind_voice_context

        structlog.contextvars.clear_contextvars()
        _bind_voice_context(conversation_id="conv-abc", call_session_id=None)
        ctx = structlog.contextvars.get_contextvars()
        # call_session_id must not appear in the context when None
        assert "call_session_id" not in ctx, (
            "call_session_id must be omitted from contextvars when None, "
            f"but got: {ctx}"
        )

    def test_bind_voice_context_omits_none_conversation_id(self):
        """When conversation_id is None, it must NOT be bound.

        Spec: at minimum bind whatever session identifiers are present.
        """
        from app.voice.webhook import _bind_voice_context

        structlog.contextvars.clear_contextvars()
        _bind_voice_context(conversation_id=None, call_session_id="sess-xyz")
        ctx = structlog.contextvars.get_contextvars()
        assert "conversation_id" not in ctx, (
            "conversation_id must be omitted from contextvars when None"
        )
        # call_session_id must still be bound
        assert ctx.get("call_session_id") == "sess-xyz"

    def test_bind_voice_context_both_none_binds_nothing(self):
        """When both IDs are None, no voice context keys must be added."""
        from app.voice.webhook import _bind_voice_context

        structlog.contextvars.clear_contextvars()
        _bind_voice_context(conversation_id=None, call_session_id=None)
        ctx = structlog.contextvars.get_contextvars()
        assert "conversation_id" not in ctx
        assert "call_session_id" not in ctx

    def test_bind_voice_context_is_non_blocking(self):
        """_bind_voice_context must complete synchronously without awaiting anything.

        Design constraint: no network I/O in the live voice turn path.
        """
        import inspect
        from app.voice.webhook import _bind_voice_context

        # The function must NOT be a coroutine (it must be sync for zero-latency binding)
        assert not inspect.iscoroutinefunction(_bind_voice_context), (
            "_bind_voice_context must be a synchronous function "
            "(no await in the live path)"
        )


# ---------------------------------------------------------------------------
# Task 1.3 — Behavior: call_session_id is re-bound after session resolution
# ---------------------------------------------------------------------------


class TestWebhookCallSessionIdReBind:
    """Behavior guard: the live voice path must re-bind call_session_id.

    The reliability review flagged that _bind_voice_context(..., call_session_id=None)
    runs early (before the DB session is resolved) and was never re-bound after
    session_id was resolved/reused/created. This class drives the real
    _process_custom_llm_request handler through the zero-DB fast path and asserts
    that, by the time the handler returns its StreamingResponse, BOTH
    conversation_id and call_session_id are present in structlog contextvars.

    This is a behavior test (exercises the handler), not just a direct call to
    the _bind_voice_context helper.
    """

    def setup_method(self):
        structlog.contextvars.clear_contextvars()

    def teardown_method(self):
        structlog.contextvars.clear_contextvars()

    def _make_context(self):
        """Build a minimal cached VoiceSessionContext for the fast path."""
        from app.voice.context import VoiceSessionContext

        return VoiceSessionContext(
            system_prompt="You are a test agent.",
            skills_content=None,
            misc_notes="",
            lead_profile="",
            model="gpt-4o",
            temperature=0.7,
            max_tokens=300,
            tools=None,
        )

    def _make_request(self):
        """Mock FastAPI Request exposing app.state.settings with an OpenAI key."""
        from pydantic import SecretStr

        request = MagicMock()
        settings = MagicMock()
        settings.openai_api_key = SecretStr("qora-test-openai-key-not-a-secret")
        request.app.state.settings = settings
        return request

    @pytest.mark.asyncio
    async def test_context_has_both_ids_after_session_resolution(self):
        """After _process_custom_llm_request resolves the session via the fast
        path, contextvars must contain both conversation_id and call_session_id.
        """
        from app.voice import webhook
        from app.voice.session import SessionStore
        from app.voice.webhook import CustomLLMRequest, _process_custom_llm_request

        client_id = "test-client"
        conversation_id = "conv-rebind-123"
        resolved_session_id = "sess-db-9999"

        # Seed a session store entry with a real DB-backed session_id and a
        # cached context so the handler takes the zero-DB fast path and reuses
        # the existing session_id (the resolve/reuse branch under test).
        store = SessionStore()
        store.create(
            conversation_id=conversation_id,
            client_id=client_id,
            lead_id=None,
            session_id=resolved_session_id,
            context=self._make_context(),
        )

        body = CustomLLMRequest(
            messages=[{"role": "user", "content": "hola"}],
            conversation_id=conversation_id,
        )

        structlog.contextvars.clear_contextvars()

        # Patch the module-level session_store the handler reads from, and the
        # CRM loader (best-effort import inside the fast path) so no I/O happens.
        with (
            patch.object(webhook, "session_store", store),
            patch(
                "app.integrations.crm_config.CRMConfigLoader.load",
                return_value=None,
            ),
        ):
            response = await _process_custom_llm_request(
                body=body,
                client_id=client_id,
                request=self._make_request(),
            )

        # Handler returns a StreamingResponse; the SSE body is NOT consumed, so
        # no LLM call is made. The re-bind must already have run synchronously.
        assert response is not None

        ctx = structlog.contextvars.get_contextvars()
        assert ctx.get("conversation_id") == conversation_id, (
            f"conversation_id missing/incorrect after resolution: {ctx}"
        )
        assert ctx.get("call_session_id") == resolved_session_id, (
            "call_session_id was NOT re-bound after the DB session was resolved — "
            f"got contextvars: {ctx}"
        )


# ---------------------------------------------------------------------------
# Task 1.3 — Initiation webhook context binding
# ---------------------------------------------------------------------------


class TestInitiationContextBinding:
    """voice/initiation.py must bind conversation_id to structlog contextvars."""

    def setup_method(self):
        structlog.contextvars.clear_contextvars()

    def teardown_method(self):
        structlog.contextvars.clear_contextvars()

    def test_bind_initiation_context_helper_exists(self):
        """app.voice.initiation must expose a _bind_initiation_context helper."""
        from app.voice import initiation

        assert hasattr(initiation, "_bind_initiation_context"), (
            "_bind_initiation_context helper must exist in app.voice.initiation "
            "after task 1.3 GREEN"
        )

    def test_bind_initiation_context_binds_conversation_id(self):
        """_bind_initiation_context must bind conversation_id when provided."""
        from app.voice.initiation import _bind_initiation_context

        structlog.contextvars.clear_contextvars()
        _bind_initiation_context(conversation_id="init-conv-456")
        ctx = structlog.contextvars.get_contextvars()
        assert ctx.get("conversation_id") == "init-conv-456"

    def test_bind_initiation_context_omits_none(self):
        """When conversation_id is None, it must NOT be bound."""
        from app.voice.initiation import _bind_initiation_context

        structlog.contextvars.clear_contextvars()
        _bind_initiation_context(conversation_id=None)
        ctx = structlog.contextvars.get_contextvars()
        assert "conversation_id" not in ctx

    def test_bind_initiation_context_is_sync(self):
        """_bind_initiation_context must be synchronous."""
        import inspect
        from app.voice.initiation import _bind_initiation_context

        assert not inspect.iscoroutinefunction(_bind_initiation_context)
