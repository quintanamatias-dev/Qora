"""TDD tests for T1 — bound and reuse the OpenAI streaming client.

Covers:
- The underlying ``AsyncOpenAI`` client must be built with an explicit, bounded
  timeout and an explicit retry budget instead of the SDK defaults
  (600s request timeout, 2 retries).
- The worst-case HTTP budget (timeout x attempts) must stay well under the 60s
  per-turn ``asyncio.timeout`` in ``app.voice.webhook``.
- The underlying ``AsyncOpenAI`` (and therefore its httpx connection pool) must
  be shared across clients with the same configuration instead of being rebuilt
  and leaked on every request.
- An upstream stall must surface as ``StreamingError`` so the webhook's
  ``generate()`` logs ``stream_error``.

All tests are fully offline: respx intercepts httpx at the transport layer.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.ai.llm_streaming import OpenAIStreamingClient, StreamingError


# The per-LLM-turn budget enforced by app.voice.webhook (asyncio.timeout(60.0)).
TURN_BUDGET_SECONDS = 60.0


def _read_timeout(client: OpenAIStreamingClient) -> float:
    """Return the effective read timeout of the underlying AsyncOpenAI client."""
    timeout = client._client.timeout
    if isinstance(timeout, httpx.Timeout):
        candidates = [
            t
            for t in (timeout.connect, timeout.read, timeout.write, timeout.pool)
            if t is not None
        ]
        assert candidates, "every httpx.Timeout component is None (unbounded)"
        return max(candidates)
    assert timeout is not None, "timeout is None (unbounded)"
    return float(timeout)


# ===========================================================================
# Bounded timeout / retries
# ===========================================================================


def test_client_has_explicit_bounded_timeout():
    """The SDK default of 600s must be replaced by a bounded timeout."""
    client = OpenAIStreamingClient(api_key="sk-test", model="gpt-4o")
    assert _read_timeout(client) < TURN_BUDGET_SECONDS


def test_client_has_explicit_retry_budget():
    """max_retries must be explicit and small, not the SDK default of 2."""
    client = OpenAIStreamingClient(api_key="sk-test", model="gpt-4o")
    assert client._client.max_retries <= 1


def test_worst_case_http_budget_fits_inside_turn_budget():
    """timeout x attempts must leave headroom inside the 60s turn budget."""
    client = OpenAIStreamingClient(api_key="sk-test", model="gpt-4o")
    attempts = client._client.max_retries + 1
    worst_case = _read_timeout(client) * attempts
    assert worst_case < TURN_BUDGET_SECONDS


def test_timeout_and_retries_are_overridable():
    """Both knobs must be constructor arguments, not hardcoded constants."""
    client = OpenAIStreamingClient(
        api_key="sk-test",
        model="gpt-4o",
        timeout=7.5,
        max_retries=0,
    )
    assert _read_timeout(client) == 7.5
    assert client._client.max_retries == 0


# ===========================================================================
# Connection pool reuse
# ===========================================================================


def test_same_configuration_reuses_underlying_openai_client():
    """No new AsyncOpenAI (and no new httpx pool) per request."""
    first = OpenAIStreamingClient(api_key="sk-reuse", model="gpt-4o")
    second = OpenAIStreamingClient(api_key="sk-reuse", model="gpt-4o")
    assert first._client is second._client


def test_different_configuration_does_not_share_client():
    """Distinct configurations must stay isolated."""
    base = OpenAIStreamingClient(api_key="sk-reuse", model="gpt-4o")
    other_key = OpenAIStreamingClient(api_key="sk-other", model="gpt-4o")
    other_timeout = OpenAIStreamingClient(
        api_key="sk-reuse", model="gpt-4o", timeout=3.0
    )
    other_retries = OpenAIStreamingClient(
        api_key="sk-reuse", model="gpt-4o", max_retries=0
    )
    assert base._client is not other_key._client
    assert base._client is not other_timeout._client
    assert base._client is not other_retries._client


@pytest.mark.asyncio
async def test_webhook_request_path_reuses_one_client():
    """Two sequential request-shaped constructions share one pool."""
    clients = [
        OpenAIStreamingClient(api_key="sk-hotpath", model="gpt-4o")._client
        for _ in range(5)
    ]
    assert len({id(c) for c in clients}) == 1


# ===========================================================================
# Stalled upstream surfaces as StreamingError
# ===========================================================================


@pytest.mark.asyncio
@respx.mock
async def test_upstream_read_timeout_surfaces_as_streaming_error():
    """A stalled upstream must raise StreamingError, not hang silently."""
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        side_effect=httpx.ReadTimeout("stalled upstream")
    )

    client = OpenAIStreamingClient(
        api_key="sk-stall",
        model="gpt-4o",
        timeout=0.5,
        max_retries=0,
    )

    with pytest.raises(StreamingError) as excinfo:
        async for _event in client.stream_events(
            messages=[{"role": "user", "content": "hola"}]
        ):
            pass

    assert "timed out" in str(excinfo.value).lower()


@pytest.mark.asyncio
async def test_streaming_error_propagates_out_of_stream_llm_response():
    """The turn-level handler only catches asyncio.TimeoutError.

    A StreamingError must therefore reach generate() in app.voice.webhook,
    which logs stream_error — it must not be swallowed on the way out.
    """
    from app.voice.webhook import _stream_llm_response

    class _StallingClient:
        async def stream_events(self, **_kwargs):
            raise StreamingError("OpenAI API timed out: stalled upstream")
            yield  # pragma: no cover - makes this an async generator

    with pytest.raises(StreamingError):
        async for _chunk in _stream_llm_response(
            client=_StallingClient(),
            messages=[{"role": "user", "content": "hola"}],
            tools=None,
            temperature=0.7,
            max_tokens=300,
            client_id="acme",
            lead_id=None,
            session_id=None,
            conversation_id=None,
        ):
            pass
