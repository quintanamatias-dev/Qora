"""Async streaming client for GPT-4o via OpenAI SSE.

Extended to support tool_calls delta accumulation and yielding alongside content.
Used by the custom LLM webhook to handle mid-stream tool execution (CAP-4, AD-4).
"""

from __future__ import annotations

import asyncio
import threading
import weakref
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Literal

import httpx
from openai import AsyncOpenAI
from openai import (
    APIConnectionError,
    APITimeoutError,
    RateLimitError,
)


# ---------------------------------------------------------------------------
# HTTP budget
# ---------------------------------------------------------------------------
#
# app.voice.webhook wraps each LLM turn in asyncio.timeout(60.0). The HTTP layer
# must fail *inside* that budget so a stalled upstream surfaces as a logged
# StreamingError instead of silently consuming the whole turn.
#
# Worst case = DEFAULT_TIMEOUT.read * (1 + DEFAULT_MAX_RETRIES) = 15s * 2 = 30s,
# which leaves ~30s of headroom under the 60s turn budget. The OpenAI SDK
# defaults (600s, 2 retries -> 1800s) are far outside it and are never used.
DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=5.0)
DEFAULT_MAX_RETRIES = 1


# ---------------------------------------------------------------------------
# Shared AsyncOpenAI clients (one httpx connection pool per configuration)
# ---------------------------------------------------------------------------
#
# Building an AsyncOpenAI per request leaks an httpx connection pool (and its
# file descriptors) on every call. Clients are cached per configuration and per
# event loop — an httpx pool is bound to the loop that first used it, so a
# cached client is never handed to a different (or closed) loop.

_client_cache: dict[tuple[Any, ...], tuple[Any, AsyncOpenAI]] = {}
_client_cache_lock = threading.Lock()


def _current_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def _get_shared_openai_client(
    api_key: str,
    model: str,
    timeout: httpx.Timeout | float,
    max_retries: int,
) -> AsyncOpenAI:
    """Return a process-wide AsyncOpenAI shared by identical configurations."""
    loop = _current_loop()
    key = (api_key, model, repr(timeout), max_retries)

    with _client_cache_lock:
        cached = _client_cache.get(key)
        if cached is not None:
            cached_loop_ref, cached_client = cached
            if loop is None:
                # Built outside a running loop; only reuse an equally loop-free entry.
                if cached_loop_ref is None:
                    return cached_client
            elif cached_loop_ref is not None and cached_loop_ref() is loop:
                if not loop.is_closed():
                    return cached_client

        client = AsyncOpenAI(
            api_key=api_key,
            timeout=timeout,
            max_retries=max_retries,
        )
        _client_cache[key] = (weakref.ref(loop) if loop is not None else None, client)
        return client


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class StreamingError(Exception):
    """Custom exception wrapping OpenAI API errors during streaming."""

    def __init__(self, message: str, original: Exception | None = None):
        super().__init__(message)
        self.original = original


# ---------------------------------------------------------------------------
# Stream event types (discriminated union via 'type' field)
# ---------------------------------------------------------------------------


@dataclass
class ContentDelta:
    """A text content token from the LLM stream."""

    type: Literal["content"] = field(default="content", init=False)
    text: str = ""


@dataclass
class ToolCallDelta:
    """A tool call accumulated from delta chunks in the stream."""

    type: Literal["tool_call"] = field(default="tool_call", init=False)
    tool_call_id: str = ""
    function_name: str = ""
    function_args: str = ""  # JSON string, accumulated


@dataclass
class StreamDone:
    """Sentinel: stream ended cleanly."""

    type: Literal["done"] = field(default="done", init=False)
    finish_reason: str = "stop"


StreamEvent = ContentDelta | ToolCallDelta | StreamDone


# ---------------------------------------------------------------------------
# Streaming Client
# ---------------------------------------------------------------------------


class OpenAIStreamingClient:
    """Async streaming client that yields typed events from GPT-4o.

    Stateless — does not store or manage conversation history.
    The caller must provide the complete messages array on each call.

    Yields StreamEvent objects:
    - ContentDelta for text tokens
    - ToolCallDelta when finish_reason == tool_calls
    - StreamDone on stream end
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        timeout: httpx.Timeout | float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ):
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._max_retries = max_retries
        self._client = _get_shared_openai_client(
            api_key=api_key,
            model=model,
            timeout=timeout,
            max_retries=max_retries,
        )

    async def stream_events(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 300,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Stream GPT-4o completion as typed events.

        Accumulates tool_call deltas and yields a single ToolCallDelta at the
        end of the stream when finish_reason == "tool_calls".

        Args:
            messages: Complete message list (system + history + user).
            tools: Optional OpenAI tools array.
            temperature: LLM temperature.
            max_tokens: Max output tokens.

        Yields:
            ContentDelta, ToolCallDelta, or StreamDone events.

        Raises:
            StreamingError: On API connection, timeout, or rate limit errors.
        """
        # Accumulator for tool_call deltas
        accumulated_tool_calls: dict[int, dict[str, Any]] = {}
        finish_reason: str = "stop"

        try:
            kwargs: dict[str, Any] = {
                "model": self._model,
                "messages": messages,
                "stream": True,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if tools:
                kwargs["tools"] = tools

            stream = await self._client.chat.completions.create(**kwargs)

            async for chunk in stream:
                for choice in chunk.choices:
                    delta = choice.delta

                    # Content token
                    if delta.content is not None:
                        yield ContentDelta(text=delta.content)

                    # Tool call deltas — accumulate
                    if delta.tool_calls:
                        for tc_delta in delta.tool_calls:
                            idx = tc_delta.index
                            if idx not in accumulated_tool_calls:
                                accumulated_tool_calls[idx] = {
                                    "id": "",
                                    "name": "",
                                    "args": "",
                                }

                            if tc_delta.id:
                                accumulated_tool_calls[idx]["id"] += tc_delta.id
                            if tc_delta.function:
                                if tc_delta.function.name:
                                    accumulated_tool_calls[idx]["name"] += (
                                        tc_delta.function.name
                                    )
                                if tc_delta.function.arguments:
                                    accumulated_tool_calls[idx]["args"] += (
                                        tc_delta.function.arguments
                                    )

                    # Track finish reason
                    if choice.finish_reason:
                        finish_reason = choice.finish_reason

        except APIConnectionError as exc:
            raise StreamingError(
                f"OpenAI API connection failed: {exc}", original=exc
            ) from exc
        except APITimeoutError as exc:
            raise StreamingError(f"OpenAI API timed out: {exc}", original=exc) from exc
        except RateLimitError as exc:
            raise StreamingError(
                f"OpenAI rate limit exceeded: {exc}", original=exc
            ) from exc

        # After stream ends: yield tool calls if any
        if finish_reason == "tool_calls" and accumulated_tool_calls:
            for _idx, tc in accumulated_tool_calls.items():
                yield ToolCallDelta(
                    tool_call_id=tc["id"],
                    function_name=tc["name"],
                    function_args=tc["args"],
                )

        yield StreamDone(finish_reason=finish_reason)

    async def stream_completion(
        self,
        messages: list[dict],
        tools: list | None = None,
    ) -> AsyncGenerator[str, None]:
        """Backward-compatible text-only stream (yields raw string tokens).

        Deprecated: prefer stream_events() for full tool call support.
        """
        async for event in self.stream_events(messages, tools=tools):
            if isinstance(event, ContentDelta):
                yield event.text
