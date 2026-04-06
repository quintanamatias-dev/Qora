"""LLM client: OpenAI GPT-4o with conversation history management.

Handles conversation context, system prompt injection, response generation,
and event emission for the voice pipeline. Includes retry logic with
exponential backoff and response truncation.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from openai import AsyncOpenAI
from openai import APIConnectionError, APITimeoutError, RateLimitError
from openai.types.chat import ChatCompletionMessageParam

logger = logging.getLogger(__name__)

# Maximum characters for TTS compatibility (ElevenLabs free-tier limit)
MAX_RESPONSE_CHARS = 2500


class LLMError(Exception):
    """Custom exception for LLM generation failures."""

    def __init__(self, message: str, original_error: Exception | None = None) -> None:
        super().__init__(message)
        self.original_error = original_error


async def _emit_event(
    event_type: str, session_id: str, payload: dict[str, Any]
) -> None:
    """Emit an event via the event bus (stub for now, wired later)."""
    logger.info(
        "event_emitted",
        extra={"event_type": event_type, "session_id": session_id, "payload": payload},
    )


class GPT4oClient:
    """Async client for OpenAI GPT-4o chat completions API.

    Manages conversation history, injects system prompts, handles
    retries, and emits events for pipeline integration.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        max_tokens: int = 300,
        temperature: float = 0.7,
        max_history_messages: int = 10,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 10.0,
        timeout: float = 10.0,
    ) -> None:
        """Initialize GPT-4o client.

        Args:
            api_key: OpenAI API key for authentication.
            model: Model name (default: gpt-4o).
            max_tokens: Maximum tokens for each response.
            temperature: Sampling temperature (0.0-1.0).
            max_history_messages: Maximum conversation history pairs to keep.
            max_retries: Maximum retry attempts on transient errors.
            base_delay: Base delay in seconds for exponential backoff.
            max_delay: Maximum delay cap in seconds.
            timeout: API call timeout in seconds.
        """
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._max_history_messages = max_history_messages
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._timeout = timeout

        # Conversation history: list of {role, content} dicts (excludes system prompt)
        self._history: list[dict[str, str]] = []

    @property
    def history(self) -> list[dict[str, str]]:
        """Return the current conversation history (without system prompt)."""
        return list(self._history)

    def append_message(self, role: str, content: str) -> None:
        """Append a message to conversation history.

        Args:
            role: Message role ("user" or "assistant").
            content: Message content text.
        """
        self._history.append({"role": role, "content": content})
        self._truncate_history()

    def _truncate_history(self) -> None:
        """Truncate history to max_history_messages * 2 entries.

        Keeps the most recent message pairs, discarding oldest entries.
        """
        max_entries = self._max_history_messages * 2
        if len(self._history) > max_entries:
            self._history = self._history[-max_entries:]

    def clear_history(self) -> None:
        """Clear all conversation history."""
        self._history.clear()

    def _build_messages(
        self, system_prompt: str, user_message: str
    ) -> list[dict[str, str]]:
        """Build the full message list with system prompt and history.

        Args:
            system_prompt: Agent's system prompt (prepended to every request).
            user_message: Latest user utterance to append.

        Returns:
            Complete message list ready for the OpenAI API.
        """
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
        ]
        messages.extend(self._history)
        messages.append({"role": "user", "content": user_message})
        return messages

    async def generate(
        self,
        messages: list[dict[str, str]],
        system_prompt: str = "",
        session_id: str = "",
    ) -> str:
        """Generate a response using GPT-4o.

        If messages already include a system prompt and full history,
        they are sent as-is. Otherwise, system_prompt is prepended.

        Args:
            messages: Message list (may be partial; system_prompt is prepended).
            system_prompt: Agent's system prompt to prepend if not already present.
            session_id: Optional session ID for event context.

        Returns:
            Generated response text, truncated to MAX_RESPONSE_CHARS.

        Raises:
            LLMError: If all retries are exhausted or an unrecoverable error occurs.
        """
        # Build final message list
        if system_prompt:
            # Check if first message is already a system prompt
            if messages and messages[0].get("role") == "system":
                full_messages = messages
            else:
                full_messages = [
                    {"role": "system", "content": system_prompt},
                    *messages,
                ]
        else:
            full_messages = messages

        last_error: Exception | None = None

        for attempt in range(self._max_retries):
            try:
                response_text = await self._call_api(full_messages)

                # Truncate response at MAX_RESPONSE_CHARS
                if len(response_text) > MAX_RESPONSE_CHARS:
                    logger.info(
                        "llm_response_truncated",
                        extra={
                            "session_id": session_id,
                            "original_length": len(response_text),
                            "truncated_length": MAX_RESPONSE_CHARS,
                        },
                    )
                    response_text = response_text[:MAX_RESPONSE_CHARS]

                # Record in history
                # Find the last user message to pair with this response
                last_user_msg = ""
                for msg in reversed(full_messages):
                    if msg.get("role") == "user":
                        last_user_msg = msg.get("content", "")
                        break

                if last_user_msg:
                    self._history.append({"role": "user", "content": last_user_msg})
                    self._history.append(
                        {"role": "assistant", "content": response_text}
                    )
                    self._truncate_history()

                await _emit_event(
                    "llm.completed",
                    session_id,
                    {"text": response_text, "token_count": None},
                )
                return response_text

            except (APIConnectionError, APITimeoutError) as e:
                last_error = e
                if attempt < self._max_retries - 1:
                    delay = min(
                        self._base_delay * (2**attempt) + random.uniform(0, 0.5),
                        self._max_delay,
                    )
                    logger.warning(
                        "llm_retry",
                        extra={
                            "session_id": session_id,
                            "attempt": attempt + 1,
                            "max_retries": self._max_retries,
                            "delay": delay,
                            "error": str(e),
                        },
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "llm_api_error",
                        extra={
                            "session_id": session_id,
                            "error_type": type(e).__name__,
                            "error_message": str(e),
                            "attempt": attempt + 1,
                            "max_retries": self._max_retries,
                        },
                        exc_info=True,
                    )

            except RateLimitError as e:
                last_error = e
                if attempt < self._max_retries - 1:
                    delay = min(
                        self._base_delay * (2 ** (attempt + 1))
                        + random.uniform(0, 1.0),
                        self._max_delay,
                    )
                    logger.warning(
                        "llm_rate_limit_retry",
                        extra={
                            "session_id": session_id,
                            "attempt": attempt + 1,
                            "delay": delay,
                        },
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "llm_rate_limit_exhausted",
                        extra={
                            "session_id": session_id,
                            "error_type": type(e).__name__,
                            "error_message": str(e),
                        },
                        exc_info=True,
                    )

            except Exception as e:
                last_error = e
                logger.error(
                    "llm_unexpected_error",
                    extra={
                        "session_id": session_id,
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                    },
                    exc_info=True,
                )
                break

        # All retries exhausted
        error_msg = f"GPT-4o API failed after {self._max_retries} retries: {last_error}"
        await _emit_event(
            "llm.error",
            session_id,
            {
                "error": str(last_error),
                "error_type": type(last_error).__name__ if last_error else "unknown",
            },
        )
        raise LLMError(error_msg, original_error=last_error)

    async def _call_api(self, messages: list[dict[str, str]]) -> str:
        """Make the actual GPT-4o API call.

        Args:
            messages: Complete message list with system prompt and history.

        Returns:
            Generated response text.
        """
        import httpx

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": m["role"], "content": m["content"]} for m in messages],  # type: ignore[list-item]
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            timeout=httpx.Timeout(self._timeout),
        )

        content = response.choices[0].message.content
        return content if content else ""
