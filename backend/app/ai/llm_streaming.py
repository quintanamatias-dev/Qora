"""Async streaming client for GPT-4o via OpenAI SSE.

Extended to support tool_calls delta accumulation and yielding alongside content.
Used by the custom LLM webhook to handle mid-stream tool execution (CAP-4, AD-4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Literal

from openai import AsyncOpenAI
from openai import (
    APIConnectionError,
    APITimeoutError,
    RateLimitError,
)


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

    def __init__(self, api_key: str, model: str = "gpt-4o"):
        self._api_key = api_key
        self._model = model
        self._client = AsyncOpenAI(api_key=api_key)

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
