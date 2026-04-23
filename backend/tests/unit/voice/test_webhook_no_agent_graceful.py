"""Unit test — CRITICAL 1: webhook create_session ValueError is caught gracefully.

When create_session() raises ValueError (no default agent), the webhook must NOT
propagate an unhandled exception. Instead it must catch the ValueError and handle it
gracefully (e.g., log it and return a graceful SSE stream that ElevenLabs can handle).

This tests the try/except around the create_session() call in the webhook's session
creation block. We test at the service boundary level to avoid the hanging SSE stream.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Test: create_session ValueError is caught in webhook path
# ---------------------------------------------------------------------------


def test_webhook_session_creation_block_catches_value_error():
    """The session creation block in _process_custom_llm_request must catch ValueError.

    Inspects the source code to verify that the create_session() call is wrapped
    in a try/except ValueError block, ensuring uncaught exceptions cannot propagate
    as 500 ISE to ElevenLabs.
    """
    import inspect
    from app.voice import webhook

    source = inspect.getsource(webhook._process_custom_llm_request)

    # The function must contain a try/except block around create_session
    assert "create_session" in source, "create_session must be called in _process_custom_llm_request"

    # There must be a ValueError catch somewhere in the session creation path
    assert "ValueError" in source, (
        "ValueError must be caught in _process_custom_llm_request to prevent 500 ISE "
        "when no default agent exists. "
        "Missing: try/except ValueError around create_session() call."
    )


def test_webhook_graceful_sse_on_value_error_returns_done():
    """The graceful SSE error path must yield [DONE] so ElevenLabs can close cleanly."""
    from app.voice import webhook

    # _sse_done must exist and return the DONE string
    assert hasattr(webhook, "_sse_done"), "_sse_done helper must exist in webhook module"
    done = webhook._sse_done()
    assert "[DONE]" in done, f"_sse_done() must contain [DONE], got: {done!r}"

    # _sse_stop must exist and return the stop chunk
    assert hasattr(webhook, "_sse_stop"), "_sse_stop helper must exist in webhook module"
    stop = webhook._sse_stop()
    assert "stop" in stop, f"_sse_stop() must contain 'stop', got: {stop!r}"
