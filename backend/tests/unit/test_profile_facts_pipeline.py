"""Unit tests for run_profile_facts_pipeline() — qora-profile-facts Phase 2.

Spec: sdd/qora-profile-facts/spec
Design: sdd/qora-profile-facts/design

Covers:
  - First-call empty state: update/remove ops discarded, only add valid
  - No-signal transcript: empty updates returned
  - GPT prompt payload: gpt-4o-mini model used, correct message structure
  - Invalid update/remove: demotion (update→add) or discard (remove)
  - DIMENSION_MODULES: profile_facts removed (Phase 2.2)
  - Helpers: _slugify, _build_pipeline_prompt, _validate_updates_against_current_facts
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock


# ===========================================================================
# Helper: _validate_updates_against_current_facts (pure function — no mocks)
# ===========================================================================


def test_validate_empty_current_facts_discards_update_and_remove():
    """When current_facts=[], update and remove ops are discarded (first call)."""
    from app.analysis.universal.profile_facts import (
        ProfileFactUpdate,
        _validate_updates_against_current_facts,
    )

    updates = [
        ProfileFactUpdate(
            operation="add",
            category="occupation",
            fact="vendedor inmobiliario",
            evidence="Said he sells real estate",
            confidence="high",
            target_fact_id=None,
        ),
        ProfileFactUpdate(
            operation="update",
            category="occupation",
            fact="gerente comercial",
            evidence="Said he was promoted",
            confidence="high",
            target_fact_id="profile:occupation:vendedor-inmobiliario",
        ),
        ProfileFactUpdate(
            operation="remove",
            category="lifestyle",
            fact="old fact",
            evidence="No longer true",
            confidence="medium",
            target_fact_id="profile:lifestyle:old-fact",
        ),
    ]

    result = _validate_updates_against_current_facts(updates, [])

    # Only the add op survives
    assert len(result) == 1
    assert result[0].operation == "add"
    assert result[0].fact == "vendedor inmobiliario"


def test_validate_keeps_add_always():
    """Add operations pass through regardless of current_facts state."""
    from app.analysis.universal.profile_facts import (
        ProfileFactUpdate,
        _validate_updates_against_current_facts,
    )

    updates = [
        ProfileFactUpdate(
            operation="add",
            category="family_context",
            fact="tiene 2 hijos",
            evidence="Mencionó que tiene dos hijos",
            confidence="high",
            target_fact_id=None,
        ),
    ]

    # With empty facts
    result_empty = _validate_updates_against_current_facts(updates, [])
    assert len(result_empty) == 1
    assert result_empty[0].operation == "add"

    # With non-empty facts
    result_with_facts = _validate_updates_against_current_facts(
        updates,
        [{"fact_key": "profile:occupation:abc", "fact_value": "other fact"}],
    )
    assert len(result_with_facts) == 1
    assert result_with_facts[0].operation == "add"


def test_validate_update_with_valid_target_fact_id_passes():
    """update op with a target_fact_id that exists in current_facts passes unchanged."""
    from app.analysis.universal.profile_facts import (
        ProfileFactUpdate,
        _validate_updates_against_current_facts,
    )

    current_facts = [
        {
            "fact_key": "profile:occupation:vendedor-inmobiliario",
            "fact_value": "vendedor",
        }
    ]
    updates = [
        ProfileFactUpdate(
            operation="update",
            category="occupation",
            fact="gerente comercial",
            evidence="Fue promovido",
            confidence="high",
            target_fact_id="profile:occupation:vendedor-inmobiliario",
        ),
    ]

    result = _validate_updates_against_current_facts(updates, current_facts)

    assert len(result) == 1
    assert result[0].operation == "update"
    assert result[0].target_fact_id == "profile:occupation:vendedor-inmobiliario"


def test_validate_update_with_invalid_target_fact_id_demoted_to_add():
    """update op with a target_fact_id NOT in current_facts is demoted to add."""
    from app.analysis.universal.profile_facts import (
        ProfileFactUpdate,
        _validate_updates_against_current_facts,
    )

    current_facts = [
        {"fact_key": "profile:occupation:other-key", "fact_value": "other fact"}
    ]
    updates = [
        ProfileFactUpdate(
            operation="update",
            category="occupation",
            fact="gerente comercial",
            evidence="Fue promovido",
            confidence="high",
            target_fact_id="profile:occupation:hallucinated-id",  # does NOT exist
        ),
    ]

    result = _validate_updates_against_current_facts(updates, current_facts)

    assert len(result) == 1
    assert result[0].operation == "add", "Should be demoted to add"
    assert result[0].target_fact_id is None, "Demoted add must have no target_fact_id"
    assert result[0].fact == "gerente comercial"


def test_validate_remove_with_valid_target_fact_id_passes():
    """remove op with a target_fact_id that exists in current_facts passes."""
    from app.analysis.universal.profile_facts import (
        ProfileFactUpdate,
        _validate_updates_against_current_facts,
    )

    current_facts = [
        {"fact_key": "profile:lifestyle:runner", "fact_value": "es corredor"}
    ]
    updates = [
        ProfileFactUpdate(
            operation="remove",
            category="lifestyle",
            fact="es corredor",
            evidence="Dijo que ya no corre más",
            confidence="high",
            target_fact_id="profile:lifestyle:runner",
        ),
    ]

    result = _validate_updates_against_current_facts(updates, current_facts)

    assert len(result) == 1
    assert result[0].operation == "remove"


def test_validate_remove_with_invalid_target_fact_id_is_discarded():
    """remove op with a target_fact_id NOT in current_facts is silently discarded."""
    from app.analysis.universal.profile_facts import (
        ProfileFactUpdate,
        _validate_updates_against_current_facts,
    )

    current_facts = [
        {"fact_key": "profile:lifestyle:runner", "fact_value": "es corredor"}
    ]
    updates = [
        ProfileFactUpdate(
            operation="remove",
            category="occupation",
            fact="some fact",
            evidence="Some evidence",
            confidence="medium",
            target_fact_id="profile:occupation:hallucinated-id",  # does NOT exist
        ),
    ]

    result = _validate_updates_against_current_facts(updates, current_facts)

    assert len(result) == 0, "Hallucinated remove should be discarded"


# ===========================================================================
# Helper: _build_pipeline_prompt (pure function)
# ===========================================================================


def test_build_pipeline_prompt_empty_facts_mentions_first_call():
    """_build_pipeline_prompt with no facts includes 'first call' notice."""
    from app.analysis.universal.profile_facts import _build_pipeline_prompt

    prompt = _build_pipeline_prompt([])

    assert "first call" in prompt.lower() or "[] (first call" in prompt
    assert "occupation" in prompt  # categories are listed


def test_build_pipeline_prompt_with_facts_includes_json_block():
    """_build_pipeline_prompt with facts serializes them as JSON."""
    from app.analysis.universal.profile_facts import _build_pipeline_prompt

    facts = [
        {
            "fact_key": "profile:occupation:vendedor-inmobiliario",
            "fact_value": "vendedor inmobiliario",
        }
    ]
    prompt = _build_pipeline_prompt(facts)

    assert "CURRENT FACTS:" in prompt
    assert "profile:occupation:vendedor-inmobiliario" in prompt


def test_build_pipeline_prompt_mentions_all_11_categories():
    """_build_pipeline_prompt includes all 11 category names."""
    from app.analysis.universal.profile_facts import _build_pipeline_prompt

    prompt = _build_pipeline_prompt([])
    categories = [
        "occupation",
        "availability",
        "communication_preference",
        "decision_style",
        "family_context",
        "lifestyle",
        "financial_attitude",
        "product_knowledge",
        "provider_relationship",
        "personality_tone",
        "other",
    ]
    for cat in categories:
        assert cat in prompt, f"Prompt must mention category '{cat}'"


# ===========================================================================
# run_profile_facts_pipeline — async pipeline (mocked OpenAI)
# ===========================================================================


@pytest.mark.asyncio
async def test_pipeline_first_call_empty_state_only_add_valid():
    """Pipeline with current_facts=[] discards update/remove GPT outputs.

    Spec: 'Pipeline runs with no prior facts (first call)'
    """
    from app.analysis.universal.profile_facts import (
        ProfileFactsAxis,
        ProfileFactUpdate,
        run_profile_facts_pipeline,
    )

    # GPT returns a mix of add, update, remove — but update/remove should be discarded
    raw_axis = ProfileFactsAxis(
        updates=[
            ProfileFactUpdate(
                operation="add",
                category="occupation",
                fact="vendedor inmobiliario",
                evidence="Trabaja vendiendo propiedades",
                confidence="high",
                target_fact_id=None,
            ),
            # This would raise ValidationError normally, so we build it through
            # raw_axis as if GPT returned it with valid target_fact_id set
            ProfileFactUpdate(
                operation="update",
                category="occupation",
                fact="gerente",
                evidence="Fue promovido",
                confidence="medium",
                target_fact_id="profile:occupation:some-key",  # won't exist in empty facts
            ),
        ]
    )

    client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = raw_axis
    client.beta.chat.completions.parse = AsyncMock(return_value=response)

    result = await run_profile_facts_pipeline(
        transcript="transcript text",
        client=client,
        current_facts=[],
    )

    # Only the add op should survive
    assert len(result.updates) == 1
    assert result.updates[0].operation == "add"
    assert result.updates[0].fact == "vendedor inmobiliario"


@pytest.mark.asyncio
async def test_pipeline_no_signal_returns_empty_updates():
    """Pipeline returns ProfileFactsAxis(updates=[]) when GPT detects no facts.

    Spec: 'Pipeline returns empty updates when no facts detected'
    """
    from app.analysis.universal.profile_facts import (
        ProfileFactsAxis,
        run_profile_facts_pipeline,
    )

    raw_axis = ProfileFactsAxis(updates=[])

    client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = raw_axis
    client.beta.chat.completions.parse = AsyncMock(return_value=response)

    result = await run_profile_facts_pipeline(
        transcript="Hola, llamo para consultar precios.",
        client=client,
        current_facts=[],
    )

    assert result.updates == []


@pytest.mark.asyncio
async def test_pipeline_uses_gpt4o_mini_model():
    """run_profile_facts_pipeline uses gpt-4o-mini model (AD-5)."""
    from app.analysis.universal.profile_facts import (
        ProfileFactsAxis,
        run_profile_facts_pipeline,
    )

    raw_axis = ProfileFactsAxis(updates=[])

    client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = raw_axis
    client.beta.chat.completions.parse = AsyncMock(return_value=response)

    await run_profile_facts_pipeline(
        transcript="some transcript",
        client=client,
        current_facts=None,
    )

    call_kwargs = client.beta.chat.completions.parse.call_args
    assert call_kwargs.kwargs.get("model") == "gpt-4o-mini" or (
        len(call_kwargs.args) > 0 and call_kwargs.args[0] == "gpt-4o-mini"
    ), f"Expected gpt-4o-mini, got {call_kwargs}"


@pytest.mark.asyncio
async def test_pipeline_prompt_includes_transcript_as_user_message():
    """Pipeline sends transcript as the user message in the chat completion."""
    from app.analysis.universal.profile_facts import (
        ProfileFactsAxis,
        run_profile_facts_pipeline,
    )

    raw_axis = ProfileFactsAxis(updates=[])
    client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = raw_axis
    client.beta.chat.completions.parse = AsyncMock(return_value=response)

    transcript = "Cliente: Soy arquitecto y trabajo desde casa."
    await run_profile_facts_pipeline(
        transcript=transcript,
        client=client,
        current_facts=None,
    )

    call_kwargs = client.beta.chat.completions.parse.call_args
    messages = call_kwargs.kwargs.get("messages", [])
    user_messages = [m for m in messages if m.get("role") == "user"]
    assert len(user_messages) == 1
    assert user_messages[0]["content"] == transcript


@pytest.mark.asyncio
async def test_pipeline_invalid_update_demoted_to_add():
    """update with non-existent target_fact_id is demoted to add.

    Spec: 'GPT hallucinates target_fact_id for update'
    """
    from app.analysis.universal.profile_facts import (
        ProfileFactsAxis,
        ProfileFactUpdate,
        run_profile_facts_pipeline,
    )

    current_facts = [
        {"fact_key": "profile:occupation:architect", "fact_value": "arquitecto"}
    ]
    raw_axis = ProfileFactsAxis(
        updates=[
            ProfileFactUpdate(
                operation="update",
                category="occupation",
                fact="ingeniero civil",
                evidence="Dijo que en realidad estudió ingeniería",
                confidence="medium",
                target_fact_id="profile:occupation:hallucinated-xyz",  # NOT in current_facts
            ),
        ]
    )

    client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = raw_axis
    client.beta.chat.completions.parse = AsyncMock(return_value=response)

    result = await run_profile_facts_pipeline(
        transcript="some transcript",
        client=client,
        current_facts=current_facts,
    )

    assert len(result.updates) == 1
    assert result.updates[0].operation == "add", "Should be demoted to add"
    assert result.updates[0].target_fact_id is None
    assert result.updates[0].fact == "ingeniero civil"


@pytest.mark.asyncio
async def test_pipeline_invalid_remove_is_discarded():
    """remove with non-existent target_fact_id is silently discarded.

    Spec: 'GPT hallucinates target_fact_id for remove'
    """
    from app.analysis.universal.profile_facts import (
        ProfileFactsAxis,
        ProfileFactUpdate,
        run_profile_facts_pipeline,
    )

    current_facts = [
        {"fact_key": "profile:occupation:architect", "fact_value": "arquitecto"}
    ]
    raw_axis = ProfileFactsAxis(
        updates=[
            ProfileFactUpdate(
                operation="remove",
                category="occupation",
                fact="ingeniero civil",
                evidence="Ya no trabaja más como ingeniero",
                confidence="high",
                target_fact_id="profile:occupation:xyz-does-not-exist",  # NOT in current_facts
            ),
        ]
    )

    client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = raw_axis
    client.beta.chat.completions.parse = AsyncMock(return_value=response)

    result = await run_profile_facts_pipeline(
        transcript="some transcript",
        client=client,
        current_facts=current_facts,
    )

    assert len(result.updates) == 0, "Hallucinated remove should be silently discarded"


@pytest.mark.asyncio
async def test_pipeline_returns_empty_axis_on_exception():
    """Pipeline returns empty ProfileFactsAxis on any exception (non-critical)."""
    from app.analysis.universal.profile_facts import (
        ProfileFactsAxis,
        run_profile_facts_pipeline,
    )

    client = AsyncMock()
    client.beta.chat.completions.parse = AsyncMock(
        side_effect=Exception("OpenAI connection error")
    )

    result = await run_profile_facts_pipeline(
        transcript="some transcript",
        client=client,
        current_facts=[],
    )

    assert isinstance(result, ProfileFactsAxis)
    assert result.updates == []


@pytest.mark.asyncio
async def test_pipeline_current_facts_none_treated_as_empty():
    """Pipeline with current_facts=None behaves like current_facts=[]."""
    from app.analysis.universal.profile_facts import (
        ProfileFactsAxis,
        ProfileFactUpdate,
        run_profile_facts_pipeline,
    )

    raw_axis = ProfileFactsAxis(
        updates=[
            ProfileFactUpdate(
                operation="add",
                category="lifestyle",
                fact="hace yoga todos los días",
                evidence="Mencionó que practica yoga",
                confidence="medium",
                target_fact_id=None,
            ),
            ProfileFactUpdate(
                operation="update",
                category="occupation",
                fact="gerente",
                evidence="Fue promovido",
                confidence="high",
                target_fact_id="profile:occupation:some-hallucinated-key",
            ),
        ]
    )

    client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = raw_axis
    client.beta.chat.completions.parse = AsyncMock(return_value=response)

    result = await run_profile_facts_pipeline(
        transcript="transcript",
        client=client,
        current_facts=None,  # None treated as []
    )

    # Only add survives; update is discarded because current_facts is effectively []
    assert len(result.updates) == 1
    assert result.updates[0].operation == "add"


# ===========================================================================
# Phase 2.2 verification: profile_facts removed from DIMENSION_MODULES
# These tests will be RED until Phase 2.2 GREEN is implemented.
# ===========================================================================


def test_profile_facts_not_in_dimension_modules():
    """profile_facts must NOT be in DIMENSION_MODULES after qora-profile-facts Phase 2.

    qora-profile-facts: removed from DIMENSION_MODULES (10 → 9 modules).
    """
    from app.analysis.universal import DIMENSION_MODULES

    names = [mod.DIMENSION["name"] for mod in DIMENSION_MODULES]
    assert "profile_facts" not in names, (
        f"profile_facts must be removed from DIMENSION_MODULES (qora-profile-facts spec). "
        f"Current modules: {names}"
    )


def test_dimension_modules_count_is_8_after_profile_facts_and_misc_notes_removal():
    """DIMENSION_MODULES has exactly 6 entries after all pipeline extractions.

    qora-profile-facts: profile_facts dimension removed (10 → 9).
    qora-misc-notes: misc_notes dimension removed (9 → 8).
    qora-data-corrections: data_corrections dimension removed (8 → 7).
    qora-next-action: next_action dimension removed (7 → 6).
    """
    from app.analysis.universal import DIMENSION_MODULES

    names = [mod.DIMENSION["name"] for mod in DIMENSION_MODULES]
    assert len(DIMENSION_MODULES) == 6, (
        f"Expected 6 DIMENSION_MODULES after qora-profile-facts, qora-misc-notes,"
        f" qora-data-corrections, and qora-next-action, "
        f"got {len(DIMENSION_MODULES)}: {names}"
    )


def test_run_profile_facts_pipeline_importable_from_universal():
    """run_profile_facts_pipeline must be importable from app.analysis.universal."""
    from app.analysis.universal import run_profile_facts_pipeline  # noqa: F401

    assert run_profile_facts_pipeline is not None
