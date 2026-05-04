"""Unit tests for misc_notes pipeline — qora-misc-notes (Issue #48).

TDD: RED → GREEN → TRIANGULATE → REFACTOR.

Covers:
- Task 1.2: _coerce_current_notes backward compat (None, str, dict, list[dict])
- Task 2.1: run_misc_notes_pipeline happy path (first call, subsequent call)
- Task 2.2: run_misc_notes_pipeline failure/backward-compat paths
"""

from __future__ import annotations

import pytest


# ===========================================================================
# Task 1.2 — _coerce_current_notes
# ===========================================================================


def test_coerce_none_returns_empty_list():
    """_coerce_current_notes(None) returns []."""
    from app.analysis.universal.misc_notes import _coerce_current_notes

    result = _coerce_current_notes(None)
    assert result == []
    assert isinstance(result, list)


def test_coerce_empty_string_returns_empty_list():
    """_coerce_current_notes('') returns []."""
    from app.analysis.universal.misc_notes import _coerce_current_notes

    result = _coerce_current_notes("")
    assert result == []


def test_coerce_whitespace_string_returns_empty_list():
    """_coerce_current_notes('   ') returns []."""
    from app.analysis.universal.misc_notes import _coerce_current_notes

    result = _coerce_current_notes("   ")
    assert result == []


def test_coerce_legacy_string_wraps_as_other_note():
    """_coerce_current_notes(str) wraps string as MiscNote(type='other', note=str)."""
    from app.analysis.universal.misc_notes import MiscNote, _coerce_current_notes

    result = _coerce_current_notes("Cliente interesado en plan enterprise")
    assert len(result) == 1
    assert isinstance(result[0], MiscNote)
    assert result[0].type == "other"
    assert result[0].note == "Cliente interesado en plan enterprise"


def test_coerce_legacy_string_different_content():
    """_coerce_current_notes wraps any non-empty string as MiscNote(type='other')."""
    from app.analysis.universal.misc_notes import _coerce_current_notes

    result = _coerce_current_notes("Prefiere contacto por WhatsApp")
    assert len(result) == 1
    assert result[0].type == "other"
    assert result[0].note == "Prefiere contacto por WhatsApp"


def test_coerce_list_of_dicts_returns_misc_notes():
    """_coerce_current_notes(list[dict]) returns list[MiscNote]."""
    from app.analysis.universal.misc_notes import MiscNote, _coerce_current_notes

    raw = [
        {"type": "pending_topic", "note": "Preguntó por precio"},
        {"type": "caution", "note": "Cliente molesto"},
    ]
    result = _coerce_current_notes(raw)
    assert len(result) == 2
    assert all(isinstance(n, MiscNote) for n in result)
    assert result[0].type == "pending_topic"
    assert result[0].note == "Preguntó por precio"
    assert result[1].type == "caution"
    assert result[1].note == "Cliente molesto"


def test_coerce_list_of_dicts_single_note():
    """_coerce_current_notes([single dict]) returns list with one MiscNote."""
    from app.analysis.universal.misc_notes import _coerce_current_notes

    raw = [{"type": "continuity", "note": "El lead tiene un Corolla 2019"}]
    result = _coerce_current_notes(raw)
    assert len(result) == 1
    assert result[0].type == "continuity"
    assert result[0].note == "El lead tiene un Corolla 2019"


def test_coerce_dict_with_notes_key():
    """_coerce_current_notes({'notes': [...]}) coerces the inner list."""
    from app.analysis.universal.misc_notes import _coerce_current_notes

    raw = {
        "notes": [
            {"type": "tone_context", "note": "Lead muy receptivo"},
        ]
    }
    result = _coerce_current_notes(raw)
    assert len(result) == 1
    assert result[0].type == "tone_context"
    assert result[0].note == "Lead muy receptivo"


def test_coerce_dict_with_empty_notes():
    """_coerce_current_notes({'notes': []}) returns []."""
    from app.analysis.universal.misc_notes import _coerce_current_notes

    result = _coerce_current_notes({"notes": []})
    assert result == []


def test_coerce_dict_without_notes_key():
    """_coerce_current_notes({'other_key': 'val'}) returns []."""
    from app.analysis.universal.misc_notes import _coerce_current_notes

    result = _coerce_current_notes({"something_else": "value"})
    assert result == []


def test_coerce_list_with_invalid_dict_skips_gracefully():
    """_coerce_current_notes skips invalid dicts without raising."""
    from app.analysis.universal.misc_notes import _coerce_current_notes

    raw = [
        {"type": "invalid_type_xyz", "note": "bad note"},  # invalid type — skipped
        {"type": "other", "note": "valid note"},
    ]
    result = _coerce_current_notes(raw)
    assert len(result) == 1
    assert result[0].note == "valid note"


def test_coerce_list_of_misc_note_objects():
    """_coerce_current_notes(list[MiscNote]) returns the same list."""
    from app.analysis.universal.misc_notes import MiscNote, _coerce_current_notes

    notes = [
        MiscNote(type="continuity", note="Ya habló con el lead"),
        MiscNote(type="other", note="Prefiere WhatsApp"),
    ]
    result = _coerce_current_notes(notes)
    assert len(result) == 2
    assert result[0] is notes[0]
    assert result[1] is notes[1]


# ===========================================================================
# Task 2.1 — run_misc_notes_pipeline happy path
# ===========================================================================


@pytest.mark.asyncio
async def test_pipeline_first_call_no_previous_notes():
    """run_misc_notes_pipeline with current_notes=[] sends transcript to GPT and returns MiscNotesAxis."""
    from unittest.mock import AsyncMock, MagicMock
    from app.analysis.universal.misc_notes import (
        MiscNote,
        MiscNotesAxis,
        run_misc_notes_pipeline,
    )

    expected_axis = MiscNotesAxis(
        notes=[MiscNote(type="pending_topic", note="Preguntó por descuento")]
    )

    client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = expected_axis
    client.beta.chat.completions.parse = AsyncMock(return_value=response)

    result = await run_misc_notes_pipeline("transcript text", client, current_notes=[])

    assert isinstance(result, MiscNotesAxis)
    assert len(result.notes) == 1
    assert result.notes[0].type == "pending_topic"
    assert result.notes[0].note == "Preguntó por descuento"
    client.beta.chat.completions.parse.assert_called_once()


@pytest.mark.asyncio
async def test_pipeline_subsequent_call_with_previous_notes():
    """run_misc_notes_pipeline with current_notes passes previous context to GPT."""
    from unittest.mock import AsyncMock, MagicMock
    from app.analysis.universal.misc_notes import (
        MiscNote,
        MiscNotesAxis,
        run_misc_notes_pipeline,
    )

    previous = [MiscNote(type="pending_topic", note="Preguntó por precio")]
    returned_axis = MiscNotesAxis(
        notes=[
            MiscNote(type="continuity", note="Descuento fue aceptado"),
        ]
    )

    client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = returned_axis
    client.beta.chat.completions.parse = AsyncMock(return_value=response)

    result = await run_misc_notes_pipeline(
        "new transcript", client, current_notes=previous
    )

    assert isinstance(result, MiscNotesAxis)
    assert len(result.notes) == 1
    assert result.notes[0].type == "continuity"
    # Verify the previous notes were included in the prompt
    call_kwargs = client.beta.chat.completions.parse.call_args
    messages = call_kwargs.kwargs["messages"]
    system_msg = messages[0]["content"]
    assert "Preguntó por precio" in system_msg


@pytest.mark.asyncio
async def test_pipeline_keeps_note_when_topic_is_ongoing():
    """Smart retention: ongoing topic keeps the existing caution note."""
    from unittest.mock import AsyncMock, MagicMock
    from app.analysis.universal.misc_notes import (
        MiscNote,
        MiscNotesAxis,
        run_misc_notes_pipeline,
    )

    previous = [MiscNote(type="caution", note="Cliente molesto por esperas")]
    transcript = "Volvió a llamar, sigue apurado y no se resolvió el tema de la espera."
    returned_axis = MiscNotesAxis(
        notes=[MiscNote(type="caution", note="Cliente molesto por esperas")]
    )

    client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = returned_axis
    client.beta.chat.completions.parse = AsyncMock(return_value=response)

    result = await run_misc_notes_pipeline(transcript, client, current_notes=previous)

    assert isinstance(result, MiscNotesAxis)
    assert len(result.notes) == 1
    assert result.notes[0].type == "caution"
    assert result.notes[0].note == "Cliente molesto por esperas"
    call_kwargs = client.beta.chat.completions.parse.call_args
    messages = call_kwargs.kwargs["messages"]
    assert messages[1]["content"] == transcript
    assert "Cliente molesto por esperas" in messages[0]["content"]


@pytest.mark.asyncio
async def test_pipeline_returns_empty_axis_on_gpt_exception():
    """run_misc_notes_pipeline returns MiscNotesAxis(notes=[]) when GPT raises."""
    from unittest.mock import AsyncMock
    from app.analysis.universal.misc_notes import MiscNotesAxis, run_misc_notes_pipeline

    client = AsyncMock()
    client.beta.chat.completions.parse = AsyncMock(side_effect=RuntimeError("GPT down"))

    result = await run_misc_notes_pipeline("transcript", client, current_notes=[])

    assert isinstance(result, MiscNotesAxis)
    assert result.notes == []


@pytest.mark.asyncio
async def test_pipeline_none_current_notes_treated_as_empty():
    """run_misc_notes_pipeline with current_notes=None treats it as first call."""
    from unittest.mock import AsyncMock, MagicMock
    from app.analysis.universal.misc_notes import MiscNotesAxis, run_misc_notes_pipeline

    empty_axis = MiscNotesAxis()

    client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = empty_axis
    client.beta.chat.completions.parse = AsyncMock(return_value=response)

    result = await run_misc_notes_pipeline("transcript", client, current_notes=None)

    assert isinstance(result, MiscNotesAxis)
    assert result.notes == []
    # Verify called — it's a first call
    client.beta.chat.completions.parse.assert_called_once()


# ===========================================================================
# Task 2.2 — run_misc_notes_pipeline failure and backward compat
# ===========================================================================


@pytest.mark.asyncio
async def test_pipeline_legacy_string_previous_notes_wrapped():
    """run_misc_notes_pipeline handles legacy str via _coerce_current_notes."""
    from unittest.mock import AsyncMock, MagicMock
    from app.analysis.universal.misc_notes import (
        MiscNote,
        MiscNotesAxis,
        _coerce_current_notes,
        run_misc_notes_pipeline,
    )

    # Simulate what the summarizer does: coerce legacy str before calling
    legacy_str = "Cliente interesado en plan enterprise"
    coerced = _coerce_current_notes(legacy_str)
    assert len(coerced) == 1
    assert coerced[0].type == "other"

    result_axis = MiscNotesAxis(
        notes=[MiscNote(type="other", note="Cliente interesado en plan enterprise")]
    )

    client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = result_axis
    client.beta.chat.completions.parse = AsyncMock(return_value=response)

    result = await run_misc_notes_pipeline(
        "new transcript", client, current_notes=coerced
    )

    assert isinstance(result, MiscNotesAxis)
    # Verify the legacy string appeared in the system prompt
    call_kwargs = client.beta.chat.completions.parse.call_args
    messages = call_kwargs.kwargs["messages"]
    system_msg = messages[0]["content"]
    assert legacy_str in system_msg


@pytest.mark.asyncio
async def test_pipeline_gpt_network_error_returns_empty():
    """run_misc_notes_pipeline swallows network errors and returns empty axis."""
    from unittest.mock import AsyncMock
    from app.analysis.universal.misc_notes import (
        MiscNote,
        MiscNotesAxis,
        run_misc_notes_pipeline,
    )

    client = AsyncMock()
    client.beta.chat.completions.parse = AsyncMock(
        side_effect=ConnectionError("network timeout")
    )

    result = await run_misc_notes_pipeline(
        "transcript",
        client,
        current_notes=[MiscNote(type="caution", note="Cliente molesto")],
    )

    assert isinstance(result, MiscNotesAxis)
    assert result.notes == []


@pytest.mark.asyncio
async def test_pipeline_empty_result_when_nothing_notable():
    """run_misc_notes_pipeline returns MiscNotesAxis(notes=[]) when GPT finds nothing."""
    from unittest.mock import AsyncMock, MagicMock
    from app.analysis.universal.misc_notes import MiscNotesAxis, run_misc_notes_pipeline

    empty_axis = MiscNotesAxis(notes=[])

    client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = empty_axis
    client.beta.chat.completions.parse = AsyncMock(return_value=response)

    result = await run_misc_notes_pipeline(
        "boring transcript", client, current_notes=[]
    )

    assert isinstance(result, MiscNotesAxis)
    assert result.notes == []
