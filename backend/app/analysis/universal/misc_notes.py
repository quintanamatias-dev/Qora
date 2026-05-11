"""Misc notes dimension — sliding-window operational memory pipeline.

qora-misc-notes: Replaced flat str notes with structured MiscNote/MiscNotesAxis
and a standalone run_misc_notes_pipeline() for stateful execution.
Previous misc_notes from extracted_facts are loaded and passed to GPT for
smart retention decisions (drop stale, keep relevant, output full rewrite).

Locale-aware: `note` text is written in the client's configured analysis_language.
`type` remains a canonical English code.
"""

from __future__ import annotations

import json
from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, Field


class MiscNote(BaseModel):
    """A single operational note for the agent."""

    type: Literal[
        "continuity",
        "pending_topic",
        "tone_context",
        "temporary_context",
        "caution",
        "other",
    ]
    note: str = Field(description="One sentence, max ~100 chars")


class MiscNotesAxis(BaseModel):
    """Sliding-window set of operational notes (max 5)."""

    notes: list[MiscNote] = Field(
        default_factory=list,
        max_length=5,
        description="Operational notes for the agent (max 5, prefer 3)",
    )


# ---------------------------------------------------------------------------
# Backward compat helper
# ---------------------------------------------------------------------------


def _coerce_current_notes(raw: str | list | dict | None) -> list[MiscNote]:
    """Coerce previous misc_notes from extracted_facts to list[MiscNote].

    Handles all legacy and new formats:
    - None / empty → []
    - str (legacy format) → [MiscNote(type="other", note=raw)]
    - list[dict] (new format) → [MiscNote(**d) for d in raw]
    - dict with "notes" key → coerce inner list
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return []
        return [MiscNote(type="other", note=stripped)]
    if isinstance(raw, dict):
        inner = raw.get("notes")
        if inner is None:
            return []
        return _coerce_current_notes(inner)
    if isinstance(raw, list):
        notes: list[MiscNote] = []
        for item in raw:
            if isinstance(item, MiscNote):
                notes.append(item)
            elif isinstance(item, dict):
                try:
                    notes.append(MiscNote(**item))
                except Exception:
                    pass
        return notes
    return []


# ---------------------------------------------------------------------------
# Pipeline prompt
# ---------------------------------------------------------------------------

_NOTE_TYPE_DESCRIPTIONS = {
    "continuity": "Context that should persist across calls (e.g. personal detail shared)",
    "pending_topic": "Something the lead asked about or needs that wasn't resolved",
    "tone_context": "Emotional tone or communication style relevant for next call",
    "temporary_context": "Transient fact (upcoming event, time constraint) that may expire",
    "caution": "Warning about lead behavior or sensitivity (e.g. irritable, skeptical)",
    "other": "Any relevant operational note that doesn't fit above categories",
}

DEFAULT_LANGUAGE = "Spanish"

_PIPELINE_SYSTEM_PROMPT = """\
You are an expert at maintaining a concise set of operational notes across sales calls.

LANGUAGE NOTE: Write each `note` in {language}. Keep `type` as one of the exact English codes listed below.

BOUNDARY RULES:
- misc_notes = TEMPORAL / OPERATIONAL context (appointments, pending topics, tone, one-call context).
- NOT stable personality traits → those go to profile_facts.
  Example: "llamar el martes" = misc_note (temporary_context).
           "consulta decisiones con su pareja" = profile_fact (NOT here).

NOTE TYPES (choose best fit):
{type_descriptions}

RETENTION RULES:
- Keep notes about topics still unresolved or actively relevant.
- Drop notes about resolved, expired, or no longer relevant topics.
- Output the FULL updated list (not just new notes — full replacement).
- Prefer 3 notes, NEVER exceed 5.
- Each note = 1 short sentence, max ~100 chars.

CURRENT NOTES (from previous call):
{current_notes_json}

Now analyze the new transcript and output the updated notes list.
"""


def _build_pipeline_prompt(
    current_notes: list[MiscNote],
    language: str = DEFAULT_LANGUAGE,
) -> str:
    """Build the system prompt with current notes serialized."""
    type_block = "\n".join(f"  {k}: {v}" for k, v in _NOTE_TYPE_DESCRIPTIONS.items())
    if current_notes:
        notes_json = json.dumps(
            [{"type": n.type, "note": n.note} for n in current_notes],
            ensure_ascii=False,
            indent=2,
        )
    else:
        notes_json = "[] (first call — generate fresh notes from transcript)"

    return _PIPELINE_SYSTEM_PROMPT.format(
        language=language,
        type_descriptions=type_block,
        current_notes_json=notes_json,
    )


# ---------------------------------------------------------------------------
# run_misc_notes_pipeline — standalone async pipeline
# ---------------------------------------------------------------------------


async def run_misc_notes_pipeline(
    transcript: str,
    client: AsyncOpenAI,
    *,
    current_notes: list[MiscNote] | None = None,
    language: str = DEFAULT_LANGUAGE,
) -> MiscNotesAxis:
    """Standalone async misc notes pipeline.

    Args:
        transcript: The call transcript text.
        client: AsyncOpenAI client instance.
        current_notes: Previous notes from Lead.extracted_facts["misc_notes"].
            Pass [] or None for the first call.
        language: Output language for `note` text.
            `type` stays as canonical English code.

    Returns:
        MiscNotesAxis with updated notes. Never raises — returns empty axis on failure.
    """
    notes = current_notes or []

    try:
        system_prompt = _build_pipeline_prompt(notes, language=language)
        response = await client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": transcript},
            ],
            response_format=MiscNotesAxis,
        )
        result: MiscNotesAxis = response.choices[0].message.parsed
        return result if result is not None else MiscNotesAxis()

    except Exception:
        # Misc notes are non-critical — return empty on any failure
        return MiscNotesAxis()
