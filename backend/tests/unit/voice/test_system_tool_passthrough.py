"""Unit tests for ElevenLabs system tool passthrough (end_call, voicemail_detection, etc.).

ElevenLabs (custom LLM mode) includes its configured system tools in the `tools` array
of each OpenAI chat-completions request. Qora must forward tool calls for tools it does
not own (passthrough) as standard OpenAI tool_calls SSE deltas instead of executing
them locally.

Tests:
- Passthrough `end_call` is forwarded as a tool_calls delta with name/args intact,
  followed by finish_reason "tool_calls" and [DONE].
- No `_execute_tool` call, no filler text, no follow-up stream for passthrough tools.
- Content streamed before the tool call is still yielded.
- Qora tool calls (e.g. load_skill) are unchanged.
- `_merge_passthrough_tools` adds request tools not present in Qora's list and ignores
  a request tool whose name collides with a Qora tool.
- No request tools → behavior identical to today.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.ai.llm_streaming import ContentDelta, StreamDone, ToolCallDelta


def _collect_sse_json(chunks: list[str]) -> list[dict]:
    """Parse SSE 'data: {...}' chunks into dicts, skipping [DONE]."""
    parsed = []
    for chunk in chunks:
        for line in chunk.strip().splitlines():
            if not line.startswith("data: "):
                continue
            raw = line[len("data: "):]
            if raw.strip() == "[DONE]":
                continue
            parsed.append(json.loads(raw))
    return parsed


# ---------------------------------------------------------------------------
# (a) + (b) + (c): passthrough end_call forwarding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_passthrough_end_call_forwarded_as_tool_calls_delta():
    """A passthrough end_call tool call is forwarded as an OpenAI tool_calls delta."""
    from app.voice.webhook import _stream_llm_response

    async def fake_stream_events(**kwargs):
        yield ContentDelta(text="Gracias por llamar, ")
        yield ToolCallDelta(
            tool_call_id="call-end-1",
            function_name="end_call",
            function_args=json.dumps({"reason": "user_requested"}),
        )
        yield StreamDone()

    mock_client = MagicMock()
    mock_client.stream_events = fake_stream_events

    with patch("app.voice.webhook._execute_tool") as mock_execute_tool:
        chunks = []
        async for chunk in _stream_llm_response(
            client=mock_client,
            messages=[{"role": "user", "content": "Chau"}],
            tools=None,
            temperature=0.7,
            max_tokens=300,
            client_id="client-1",
            lead_id=None,
            session_id=None,
            conversation_id="conv-1",
            passthrough_tool_names={"end_call"},
        ):
            chunks.append(chunk)

        # (b) no local execution
        mock_execute_tool.assert_not_called()

    events = _collect_sse_json(chunks)

    # (c) content streamed before the tool call is still present
    content_deltas = [
        e["choices"][0]["delta"].get("content")
        for e in events
        if "content" in e["choices"][0]["delta"]
    ]
    assert "Gracias por llamar, " in content_deltas

    # (a) tool_calls delta carries the forwarded name + arguments intact
    tool_call_events = [
        e for e in events if "tool_calls" in e["choices"][0]["delta"]
    ]
    assert len(tool_call_events) == 1
    forwarded = tool_call_events[0]["choices"][0]["delta"]["tool_calls"][0]
    assert forwarded["type"] == "function"
    assert forwarded["function"]["name"] == "end_call"
    assert json.loads(forwarded["function"]["arguments"]) == {"reason": "user_requested"}
    assert forwarded["id"] == "call-end-1"

    # finish_reason "tool_calls" chunk follows
    finish_reasons = [e["choices"][0].get("finish_reason") for e in events]
    assert "tool_calls" in finish_reasons

    # [DONE] terminator present
    assert any("[DONE]" in c for c in chunks)

    # (b) no filler text chunk and no follow-up stream — filler phrases never appear
    for delta_content in content_deltas:
        assert delta_content is not None
        assert "momento" not in delta_content.lower()


@pytest.mark.asyncio
async def test_passthrough_tool_does_not_emit_sse_stop_finish_reason():
    """Passthrough handling must not also emit a finish_reason='stop' chunk."""
    from app.voice.webhook import _stream_llm_response

    async def fake_stream_events(**kwargs):
        yield ToolCallDelta(
            tool_call_id="call-end-2",
            function_name="end_call",
            function_args=json.dumps({"reason": "done"}),
        )
        yield StreamDone()

    mock_client = MagicMock()
    mock_client.stream_events = fake_stream_events

    with patch("app.voice.webhook._execute_tool"):
        chunks = []
        async for chunk in _stream_llm_response(
            client=mock_client,
            messages=[{"role": "user", "content": "Chau"}],
            tools=None,
            temperature=0.7,
            max_tokens=300,
            client_id="client-1",
            lead_id=None,
            session_id=None,
            conversation_id="conv-2",
            passthrough_tool_names={"end_call"},
        ):
            chunks.append(chunk)

    events = _collect_sse_json(chunks)
    finish_reasons = [e["choices"][0].get("finish_reason") for e in events]
    assert finish_reasons.count("stop") == 0
    assert finish_reasons.count("tool_calls") == 1


@pytest.mark.asyncio
async def test_passthrough_tool_no_follow_up_stream_call():
    """Passthrough handling must not re-invoke client.stream_events for a follow-up."""
    from app.voice.webhook import _stream_llm_response

    call_count = {"n": 0}

    async def fake_stream_events(**kwargs):
        call_count["n"] += 1
        yield ToolCallDelta(
            tool_call_id="call-end-3",
            function_name="end_call",
            function_args=json.dumps({"reason": "done"}),
        )
        yield StreamDone()

    mock_client = MagicMock()
    mock_client.stream_events = fake_stream_events

    with patch("app.voice.webhook._execute_tool"):
        async for _chunk in _stream_llm_response(
            client=mock_client,
            messages=[{"role": "user", "content": "Chau"}],
            tools=None,
            temperature=0.7,
            max_tokens=300,
            client_id="client-1",
            lead_id=None,
            session_id=None,
            conversation_id="conv-3",
            passthrough_tool_names={"end_call"},
        ):
            pass

    # stream_events invoked exactly once (no follow-up call for passthrough tools)
    assert call_count["n"] == 1


# ---------------------------------------------------------------------------
# (d) Qora tool calls remain unchanged when passthrough_tool_names is empty/absent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_qora_tool_call_unchanged_when_not_passthrough():
    """load_skill (a Qora tool) is executed locally and unaffected by passthrough logic."""
    from app.prompts.skill_loader import SkillRegistryEntry
    from app.voice.webhook import _stream_llm_response

    registry_entries = [
        SkillRegistryEntry(
            name="qora-info",
            description="Qora platform info",
            trigger_hint="About Qora",
            filler_text="Dejame revisar eso...",
        )
    ]

    async def fake_stream_events(**kwargs):
        yield ToolCallDelta(
            tool_call_id="call-skill-1",
            function_name="load_skill",
            function_args=json.dumps({"skill_name": "qora-info"}),
        )
        yield StreamDone()

    mock_client = MagicMock()
    mock_client.stream_events = fake_stream_events

    async def fake_execute_tool(tool_name, tool_args, client_id, lead_id, **kwargs):
        return "# Qora Info\nContent."

    with patch("app.voice.webhook._execute_tool", side_effect=fake_execute_tool) as mock_execute:
        chunks = []
        async for chunk in _stream_llm_response(
            client=mock_client,
            messages=[{"role": "user", "content": "Hola"}],
            tools=None,
            temperature=0.7,
            max_tokens=300,
            client_id="client-1",
            lead_id=None,
            session_id=None,
            conversation_id="conv-4",
            registry_entries=registry_entries,
            passthrough_tool_names={"end_call"},  # unrelated passthrough name present
        ):
            chunks.append(chunk)

    mock_execute.assert_called_once()
    events = _collect_sse_json(chunks)
    # No tool_calls delta forwarded — it was executed locally like before
    tool_call_events = [e for e in events if "tool_calls" in e["choices"][0]["delta"]]
    assert tool_call_events == []
    finish_reasons = [e["choices"][0].get("finish_reason") for e in events]
    assert "stop" in finish_reasons
    assert "tool_calls" not in finish_reasons


# ---------------------------------------------------------------------------
# (e) + (f) _merge_passthrough_tools helper
# ---------------------------------------------------------------------------


def test_merge_passthrough_tools_adds_request_tool_not_in_qora_list():
    """A request tool whose name is not a Qora tool is added as passthrough."""
    from app.voice.webhook import _merge_passthrough_tools

    qora_tools = [{"type": "function", "function": {"name": "load_skill"}}]
    request_tools = [{"type": "function", "function": {"name": "end_call"}}]

    merged, passthrough_names = _merge_passthrough_tools(qora_tools, request_tools)

    names = [t["function"]["name"] for t in merged]
    assert "load_skill" in names
    assert "end_call" in names
    assert passthrough_names == {"end_call"}


def test_merge_passthrough_tools_ignores_name_collision_with_qora_tool():
    """A request tool whose name collides with a Qora tool is ignored; Qora wins."""
    from app.voice.webhook import _merge_passthrough_tools

    qora_tools = [
        {"type": "function", "function": {"name": "load_skill", "description": "qora version"}}
    ]
    request_tools = [
        {"type": "function", "function": {"name": "load_skill", "description": "el version"}}
    ]

    merged, passthrough_names = _merge_passthrough_tools(qora_tools, request_tools)

    assert len(merged) == 1
    assert merged[0]["function"]["description"] == "qora version"
    assert passthrough_names == set()


def test_merge_passthrough_tools_no_request_tools_identical_to_today():
    """No request tools → merged tools and passthrough names are unchanged/empty."""
    from app.voice.webhook import _merge_passthrough_tools

    qora_tools = [{"type": "function", "function": {"name": "load_skill"}}]

    merged, passthrough_names = _merge_passthrough_tools(qora_tools, None)

    assert merged == qora_tools
    assert passthrough_names == set()

    merged_none, passthrough_names_none = _merge_passthrough_tools(None, None)
    assert merged_none is None
    assert passthrough_names_none == set()
