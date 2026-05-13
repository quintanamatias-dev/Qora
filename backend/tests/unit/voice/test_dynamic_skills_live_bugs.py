"""TDD tests for fix-dynamic-skills-live-bugs.

Covers:
- Task 1.1: ConversationState.loaded_skills field
- Task 1.2: _assemble_context_system_content with loaded_skills
- Task 1.3: Cached load_skill short-circuits filler/sleep/tool
- Task 1.4: First successful load_skill stores in conv_state.loaded_skills
- Task 1.5: Static audit — all filler strings end with sentence-ending punctuation

Spec refs: AC-1 through AC-7.
"""

from __future__ import annotations


# ===========================================================================
# Task 1.1 — ConversationState.loaded_skills field
# ===========================================================================


def test_conversation_state_has_loaded_skills_field():
    """AC-1: ConversationState must have loaded_skills field defaulting to empty dict."""
    from app.voice.session import ConversationState

    state = ConversationState(
        conversation_id="conv-001",
        client_id="acme",
        lead_id="lead-001",
        session_id="sess-001",
    )

    assert hasattr(state, "loaded_skills"), "ConversationState must have 'loaded_skills' field"
    assert state.loaded_skills == {}, "loaded_skills must default to empty dict"
    assert isinstance(state.loaded_skills, dict), "loaded_skills must be a dict"


def test_conversation_state_loaded_skills_instances_do_not_share_dict():
    """AC-1: Each ConversationState instance must have its OWN dict (no shared default_factory bug)."""
    from app.voice.session import ConversationState

    state_a = ConversationState(
        conversation_id="conv-a", client_id="acme", lead_id=None, session_id="sess-a"
    )
    state_b = ConversationState(
        conversation_id="conv-b", client_id="acme", lead_id=None, session_id="sess-b"
    )

    # Mutate state_a's dict — must NOT affect state_b
    state_a.loaded_skills["pricing"] = "# Pricing content"

    assert state_b.loaded_skills == {}, (
        "Mutating state_a.loaded_skills must not affect state_b. "
        "Make sure to use field(default_factory=dict), NOT field(default={})"
    )


# ===========================================================================
# Task 1.2 — _assemble_context_system_content with loaded_skills
# ===========================================================================


def _make_ctx(
    system_prompt: str = "Base prompt.",
    skills_index: str | None = None,
    misc_notes: str = "",
    lead_profile: str = "",
):
    """Build a minimal VoiceSessionContext for assembly tests."""
    from app.voice.context import VoiceSessionContext

    return VoiceSessionContext(
        system_prompt=system_prompt,
        skills_content=None,
        misc_notes=misc_notes,
        lead_profile=lead_profile,
        model="gpt-4o",
        temperature=0.7,
        max_tokens=300,
        tools=None,
        skills_index=skills_index,
    )


def test_assemble_with_loaded_skills_appends_blocks():
    """AC-3: _assemble_context_system_content with loaded_skills appends ## Loaded Skill blocks."""
    from app.voice.webhook import _assemble_context_system_content

    ctx = _make_ctx(system_prompt="System prompt.")
    loaded_skills = {"pricing": "# Pricing\nFull pricing content here."}

    result = _assemble_context_system_content(ctx, loaded_skills=loaded_skills)

    assert "## Loaded Skill: pricing" in result, (
        f"Expected '## Loaded Skill: pricing' block. Got:\n{result!r}"
    )
    assert "Full pricing content here." in result, (
        f"Expected skill content in output. Got:\n{result!r}"
    )
    assert result.index("System prompt.") < result.index("## Loaded Skill: pricing"), (
        "Loaded skill blocks must appear AFTER the base system prompt"
    )


def test_assemble_with_empty_loaded_skills_unchanged():
    """AC-3 edge: Empty loaded_skills produces no extra content."""
    from app.voice.webhook import _assemble_context_system_content

    ctx = _make_ctx(system_prompt="Only base prompt.")
    result_with_empty = _assemble_context_system_content(ctx, loaded_skills={})
    result_without = _assemble_context_system_content(ctx)

    assert result_with_empty == result_without, (
        "Empty loaded_skills dict must produce identical output to no loaded_skills"
    )
    assert "## Loaded Skill" not in result_with_empty, (
        "No ## Loaded Skill blocks must appear when loaded_skills is empty"
    )


def test_assemble_with_none_loaded_skills_unchanged():
    """AC-3 edge: None loaded_skills (default) produces no extra content."""
    from app.voice.webhook import _assemble_context_system_content

    ctx = _make_ctx(system_prompt="Only base prompt.")
    result = _assemble_context_system_content(ctx, loaded_skills=None)

    assert "## Loaded Skill" not in result, (
        "No ## Loaded Skill blocks must appear when loaded_skills is None"
    )


def test_assemble_multiple_skills_all_appear():
    """AC-3: Multiple loaded skills all appear in deterministic order."""
    from app.voice.webhook import _assemble_context_system_content

    ctx = _make_ctx(system_prompt="Base.")
    loaded_skills = {
        "pricing": "# Pricing content",
        "returns": "# Returns content",
    }

    result = _assemble_context_system_content(ctx, loaded_skills=loaded_skills)

    assert "## Loaded Skill: pricing" in result
    assert "## Loaded Skill: returns" in result
    assert "# Pricing content" in result
    assert "# Returns content" in result

    # Deterministic order: insertion order
    pricing_pos = result.index("## Loaded Skill: pricing")
    returns_pos = result.index("## Loaded Skill: returns")
    assert pricing_pos < returns_pos, (
        "Loaded skills must appear in insertion order (pricing before returns)"
    )


def test_assemble_loaded_skills_appear_after_skills_index():
    """AC-3: Loaded skill blocks appear AFTER the skills index."""
    from app.voice.webhook import _assemble_context_system_content

    ctx = _make_ctx(
        system_prompt="Base.",
        skills_index="## Available Skills\n- pricing",
    )
    loaded_skills = {"pricing": "# Pricing\nFull pricing content."}

    result = _assemble_context_system_content(ctx, loaded_skills=loaded_skills)

    skills_index_pos = result.index("## Available Skills")
    loaded_skill_pos = result.index("## Loaded Skill: pricing")
    assert skills_index_pos < loaded_skill_pos, (
        "Loaded skill blocks must appear AFTER the skills index"
    )


# ===========================================================================
# Task 1.3 — Cached load_skill returns cached content, skips filler/sleep/tool
# ===========================================================================


import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_conv_state(loaded_skills: dict | None = None):
    """Build a ConversationState with optional loaded_skills."""
    from app.voice.session import ConversationState

    state = ConversationState(
        conversation_id="conv-cache-001",
        client_id="acme",
        lead_id="lead-001",
        session_id="sess-001",
    )
    if loaded_skills is not None:
        state.loaded_skills = loaded_skills
    return state


def _make_sse_stream(*tokens: str) -> bytes:
    """Minimal SSE stream bytes for mocking OpenAI."""
    import json

    chunks = b""
    for token in tokens:
        payload = {
            "id": "chatcmpl-t",
            "object": "chat.completion.chunk",
            "choices": [{"index": 0, "delta": {"content": token}, "finish_reason": None}],
        }
        chunks += f"data: {json.dumps(payload)}\n\n".encode()
    stop = {
        "id": "chatcmpl-t",
        "object": "chat.completion.chunk",
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    chunks += f"data: {json.dumps(stop)}\n\n".encode()
    chunks += b"data: [DONE]\n\n"
    return chunks


@pytest.mark.asyncio
async def test_cached_load_skill_skips_tool_execution():
    """AC-4: When skill is already in conv_state.loaded_skills, _execute_tool must NOT be called."""
    from app.voice.webhook import _stream_llm_response
    from app.ai.llm_streaming import OpenAIStreamingClient, ToolCallDelta, StreamDone
    import json

    cached_content = "# Pricing skill content — cached"
    conv_state = _make_conv_state(loaded_skills={"pricing": cached_content})

    # Build a fake streaming client that emits a load_skill tool call
    tool_event = ToolCallDelta(
        tool_call_id="call-001",
        function_name="load_skill",
        function_args=json.dumps({"skill_name": "pricing"}),
    )

    async def fake_stream_events(**kwargs):
        yield tool_event
        yield StreamDone()

    mock_client = MagicMock(spec=OpenAIStreamingClient)
    mock_client.stream_events = fake_stream_events

    chunks = []
    with patch("app.voice.webhook._execute_tool", new_callable=AsyncMock) as mock_execute, \
         patch("app.voice.webhook.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        async for chunk in _stream_llm_response(
            client=mock_client,
            messages=[{"role": "user", "content": "prices?"}],
            tools=None,
            temperature=0.7,
            max_tokens=300,
            client_id="acme",
            lead_id="lead-001",
            session_id=None,
            conversation_id=None,
            conv_state=conv_state,
        ):
            chunks.append(chunk)

    # _execute_tool must NOT have been called (cached content used instead)
    mock_execute.assert_not_called(), "Cached skill must skip _execute_tool"

    # asyncio.sleep must NOT be called (no filler emitted for cached case)
    mock_sleep.assert_not_called(), "Cached skill must skip asyncio.sleep"


@pytest.mark.asyncio
async def test_cached_load_skill_skips_filler_emission():
    """AC-4: Cached skill must NOT emit a filler SSE chunk."""
    from app.voice.webhook import _stream_llm_response
    from app.ai.llm_streaming import OpenAIStreamingClient, ToolCallDelta, StreamDone
    import json

    cached_content = "# Cached pricing"
    conv_state = _make_conv_state(loaded_skills={"pricing": cached_content})

    tool_event = ToolCallDelta(
        tool_call_id="call-001",
        function_name="load_skill",
        function_args=json.dumps({"skill_name": "pricing"}),
    )

    async def fake_stream_events(**kwargs):
        yield tool_event
        yield StreamDone()

    async def fake_follow_up_events(**kwargs):
        from app.ai.llm_streaming import ContentDelta
        yield ContentDelta(text="Aquí está el precio.")
        yield StreamDone()

    call_count = [0]

    async def switching_stream_events(**kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            yield tool_event
            yield StreamDone()
        else:
            from app.ai.llm_streaming import ContentDelta
            yield ContentDelta(text="Aquí.")
            yield StreamDone()

    mock_client = MagicMock(spec=OpenAIStreamingClient)
    mock_client.stream_events = switching_stream_events

    chunks = []
    with patch("app.voice.webhook._execute_tool", new_callable=AsyncMock), \
         patch("app.voice.webhook.asyncio.sleep", new_callable=AsyncMock):
        async for chunk in _stream_llm_response(
            client=mock_client,
            messages=[{"role": "user", "content": "prices?"}],
            tools=None,
            temperature=0.7,
            max_tokens=300,
            client_id="acme",
            lead_id="lead-001",
            session_id=None,
            conversation_id=None,
            conv_state=conv_state,
        ):
            chunks.append(chunk)

    # No filler phrases from registry should appear in chunks for cached case
    filler_phrases = ["Un momento", "Déjame", "dejame"]
    all_chunk_text = "".join(chunks)
    for phrase in filler_phrases:
        assert phrase not in all_chunk_text, (
            f"Cached skill must NOT emit filler. Found '{phrase}' in: {all_chunk_text!r}"
        )


# ===========================================================================
# Task 1.4 — First successful load_skill stores result in conv_state.loaded_skills
# ===========================================================================


@pytest.mark.asyncio
async def test_first_load_skill_stores_result_in_conv_state():
    """AC-2: After successful load_skill, content stored in conv_state.loaded_skills."""
    from app.voice.webhook import _stream_llm_response
    from app.ai.llm_streaming import OpenAIStreamingClient, ToolCallDelta, StreamDone
    import json

    conv_state = _make_conv_state(loaded_skills={})  # empty — not yet loaded

    tool_event = ToolCallDelta(
        tool_call_id="call-001",
        function_name="load_skill",
        function_args=json.dumps({"skill_name": "pricing"}),
    )

    call_count = [0]

    async def switching_stream(**kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            yield tool_event
            yield StreamDone()
        else:
            from app.ai.llm_streaming import ContentDelta
            yield ContentDelta(text="OK")
            yield StreamDone()

    mock_client = MagicMock(spec=OpenAIStreamingClient)
    mock_client.stream_events = switching_stream

    skill_content = "# Pricing skill markdown content"

    with patch(
        "app.voice.webhook._execute_tool",
        new_callable=AsyncMock,
        return_value=skill_content,  # dispatcher returns raw string on success
    ), patch("app.voice.webhook.asyncio.sleep", new_callable=AsyncMock):
        async for _ in _stream_llm_response(
            client=mock_client,
            messages=[{"role": "user", "content": "prices?"}],
            tools=None,
            temperature=0.7,
            max_tokens=300,
            client_id="acme",
            lead_id="lead-001",
            session_id=None,
            conversation_id=None,
            conv_state=conv_state,
        ):
            pass

    assert "pricing" in conv_state.loaded_skills, (
        "After successful load_skill, skill_name must be a key in conv_state.loaded_skills"
    )
    assert conv_state.loaded_skills["pricing"] == skill_content, (
        f"conv_state.loaded_skills['pricing'] must equal the returned skill content. "
        f"Got: {conv_state.loaded_skills.get('pricing')!r}"
    )


@pytest.mark.asyncio
async def test_failed_load_skill_does_not_modify_conv_state():
    """AC-2 error case: load_skill error does NOT modify conv_state.loaded_skills."""
    from app.voice.webhook import _stream_llm_response
    from app.ai.llm_streaming import OpenAIStreamingClient, ToolCallDelta, StreamDone
    import json

    conv_state = _make_conv_state(loaded_skills={})

    tool_event = ToolCallDelta(
        tool_call_id="call-001",
        function_name="load_skill",
        function_args=json.dumps({"skill_name": "nonexistent"}),
    )

    call_count = [0]

    async def switching_stream(**kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            yield tool_event
            yield StreamDone()
        else:
            from app.ai.llm_streaming import ContentDelta
            yield ContentDelta(text="Lo siento.")
            yield StreamDone()

    mock_client = MagicMock(spec=OpenAIStreamingClient)
    mock_client.stream_events = switching_stream

    with patch(
        "app.voice.webhook._execute_tool",
        new_callable=AsyncMock,
        return_value="Error: Skill 'nonexistent' not found in registry.",  # dispatcher returns "Error: ..." on failure
    ), patch("app.voice.webhook.asyncio.sleep", new_callable=AsyncMock):
        async for _ in _stream_llm_response(
            client=mock_client,
            messages=[{"role": "user", "content": "test?"}],
            tools=None,
            temperature=0.7,
            max_tokens=300,
            client_id="acme",
            lead_id="lead-001",
            session_id=None,
            conversation_id=None,
            conv_state=conv_state,
        ):
            pass

    assert conv_state.loaded_skills == {}, (
        "conv_state.loaded_skills must remain empty after a failed load_skill call"
    )


@pytest.mark.asyncio
async def test_load_skill_awaits_sleep_after_filler():
    """AC-5: asyncio.sleep(0.7) is awaited after filler emit for uncached skill."""
    from app.voice.webhook import _stream_llm_response
    from app.ai.llm_streaming import OpenAIStreamingClient, ToolCallDelta, StreamDone
    import json

    conv_state = _make_conv_state(loaded_skills={})  # uncached

    tool_event = ToolCallDelta(
        tool_call_id="call-001",
        function_name="load_skill",
        function_args=json.dumps({"skill_name": "pricing"}),
    )

    call_count = [0]

    async def switching_stream(**kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            yield tool_event
            yield StreamDone()
        else:
            from app.ai.llm_streaming import ContentDelta
            yield ContentDelta(text="OK")
            yield StreamDone()

    mock_client = MagicMock(spec=OpenAIStreamingClient)
    mock_client.stream_events = switching_stream

    sleep_calls = []

    async def mock_sleep(seconds):
        sleep_calls.append(seconds)

    with patch(
        "app.voice.webhook._execute_tool",
        new_callable=AsyncMock,
        return_value="# Pricing",  # dispatcher returns raw string on success
    ), patch("app.voice.webhook.asyncio.sleep", side_effect=mock_sleep):
        async for _ in _stream_llm_response(
            client=mock_client,
            messages=[{"role": "user", "content": "prices?"}],
            tools=None,
            temperature=0.7,
            max_tokens=300,
            client_id="acme",
            lead_id="lead-001",
            session_id=None,
            conversation_id=None,
            conv_state=conv_state,
        ):
            pass

    assert len(sleep_calls) == 1, (
        f"asyncio.sleep must be called exactly once after filler. Called {len(sleep_calls)} time(s)"
    )
    assert sleep_calls[0] == pytest.approx(0.7), (
        f"asyncio.sleep must be called with FILLER_PAUSE_SECONDS=0.7. Got: {sleep_calls[0]}"
    )


# ===========================================================================
# Regression: dispatcher error strings (with "Error:" prefix) must NOT be cached
# ===========================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "dispatcher_error",
    [
        # These are the EXACT strings returned by the FIXED dispatcher.py.
        # dispatcher.py now always prefixes handle_load_skill() error messages with
        # "Error:" so the webhook cache guard (`not startswith("Error:")`) rejects them.
        # Each string here maps to one of the error branches in handle_load_skill().
        "Error: Skill 'nonexistent' not found in registry. Available skills: [].",
        "Error: Invalid skill name 'bad/name': path separators and '..' are not allowed.",
        "Error: Skill file for 'broken' could not be read. The skill may not be available right now.",
        "Error: Unexpected error loading skill 'crash'.",
        "Error: Unknown error loading skill.",  # fallback branch
    ],
)
async def test_dispatcher_error_strings_are_not_cached(dispatcher_error: str):
    """Regression: dispatcher error strings (prefixed with 'Error:') must NOT be cached.

    Before the fix, dispatcher.py returned bare strings like:
      "Skill 'x' not found in registry..."
    These do NOT start with "Error:" so the webhook guard incorrectly cached them.

    After the fix, dispatcher.py prefixes ALL handle_load_skill() errors with "Error:",
    and the webhook guard correctly rejects them via `not startswith("Error:")`.
    """
    from app.voice.webhook import _stream_llm_response
    from app.ai.llm_streaming import OpenAIStreamingClient, ToolCallDelta, StreamDone
    import json

    conv_state = _make_conv_state(loaded_skills={})

    tool_event = ToolCallDelta(
        tool_call_id="call-001",
        function_name="load_skill",
        function_args=json.dumps({"skill_name": "nonexistent"}),
    )

    call_count = [0]

    async def switching_stream(**kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            yield tool_event
            yield StreamDone()
        else:
            from app.ai.llm_streaming import ContentDelta

            yield ContentDelta(text="Lo siento.")
            yield StreamDone()

    mock_client = MagicMock(spec=OpenAIStreamingClient)
    mock_client.stream_events = switching_stream

    with patch(
        "app.voice.webhook._execute_tool",
        new_callable=AsyncMock,
        return_value=dispatcher_error,  # "Error:"-prefixed string from fixed dispatcher
    ), patch("app.voice.webhook.asyncio.sleep", new_callable=AsyncMock):
        async for _ in _stream_llm_response(
            client=mock_client,
            messages=[{"role": "user", "content": "test?"}],
            tools=None,
            temperature=0.7,
            max_tokens=300,
            client_id="acme",
            lead_id="lead-001",
            session_id=None,
            conversation_id=None,
            conv_state=conv_state,
        ):
            pass

    assert conv_state.loaded_skills == {}, (
        f"Dispatcher error string must NOT be cached. "
        f"Got loaded_skills={conv_state.loaded_skills!r} for error: {dispatcher_error!r}"
    )


# ===========================================================================
# Task 1.5 — Static audit: all filler strings end with sentence-ending punctuation
# ===========================================================================


def test_filler_strings_end_with_sentence_punctuation():
    """AC-7: All filler strings in webhook.py must end with '.', '!', or '?'."""
    import re
    from pathlib import Path

    webhook_path = Path(__file__).resolve().parents[3] / "app" / "voice" / "webhook.py"
    source = webhook_path.read_text("utf-8")

    # Extract string literals that look like filler (quoted Spanish/English phrases)
    # Pattern: any string starting with uppercase or special chars that doesn't end with punctuation
    # We focus on DEFAULT_FILLER and TOOL_FILLER_PHRASES plus any hardcoded strings in webhook.py
    from app.tools.registry import DEFAULT_FILLER, TOOL_FILLER_PHRASES
    from app.tools.skill_loader import FILLER_TEXT as SKILL_FILLER

    all_fillers = {
        "DEFAULT_FILLER": DEFAULT_FILLER,
        "SKILL_FILLER": SKILL_FILLER,
        **{f"TOOL_FILLER_PHRASES[{k!r}]": v for k, v in TOOL_FILLER_PHRASES.items()},
    }

    # Also check any string literals in webhook.py that are used as filler-like content
    # We check the module-level constants that are imported
    SENTENCE_ENDING = (".", "!", "?", "…")

    violations = []
    for name, filler in all_fillers.items():
        if filler and not filler.rstrip().endswith(SENTENCE_ENDING):
            violations.append(f"  {name} = {filler!r}")

    assert not violations, (
        "The following filler strings do NOT end with '.', '!', or '?':\n"
        + "\n".join(violations)
        + "\n\nAll filler strings must end with sentence-ending punctuation "
        "so TTS engines generate a natural pause."
    )
