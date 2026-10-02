"""Unit tests for qora-profile-facts memory injection.

Covers:
- is_lead_evidence: pure speaker-attribution helper
- run_profile_facts_pipeline: drops add-ops with agent-only evidence, keeps
  add-ops with lead evidence
- _assemble_context_system_content: profile_facts_block renders after
  lead_profile and before loaded skill blocks; omitted when empty
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# is_lead_evidence — pure helper
# ---------------------------------------------------------------------------


def test_is_lead_evidence_true_for_lead_line():
    from app.analysis.universal.profile_facts import is_lead_evidence

    evidence = "Lead: Uy, pará, pará, no me des tanta info de una."
    assert is_lead_evidence(evidence) is True


def test_is_lead_evidence_false_for_agent_only_line():
    from app.analysis.universal.profile_facts import is_lead_evidence

    evidence = "Agente: Perfecto, te la van a mandar por WhatsApp entonces."
    assert is_lead_evidence(evidence) is False


def test_is_lead_evidence_false_for_empty():
    from app.analysis.universal.profile_facts import is_lead_evidence

    assert is_lead_evidence("") is False
    assert is_lead_evidence("   ") is False


# ---------------------------------------------------------------------------
# run_profile_facts_pipeline — write-time quality gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_drops_add_op_with_agent_only_evidence():
    """An add-op whose evidence is the agent's own line is dropped."""
    from app.analysis.universal.profile_facts import (
        ProfileFactsAxis,
        ProfileFactUpdate,
        run_profile_facts_pipeline,
    )

    raw_axis = ProfileFactsAxis(
        updates=[
            ProfileFactUpdate(
                operation="add",
                category="communication_preference",
                fact="prefers WhatsApp",
                evidence="Agente: Perfecto, te la van a mandar por WhatsApp.",
                confidence="medium",
                target_fact_id=None,
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

    assert result.updates == []


@pytest.mark.asyncio
async def test_pipeline_keeps_add_op_with_lead_evidence():
    """An add-op whose evidence is attributed to the lead is kept."""
    from app.analysis.universal.profile_facts import (
        ProfileFactsAxis,
        ProfileFactUpdate,
        run_profile_facts_pipeline,
    )

    raw_axis = ProfileFactsAxis(
        updates=[
            ProfileFactUpdate(
                operation="add",
                category="personality_tone",
                fact="prefers short explanations",
                evidence="Lead: Uy, pará, pará, no me des tanta info de una.",
                confidence="high",
                target_fact_id=None,
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

    assert len(result.updates) == 1
    assert result.updates[0].fact == "prefers short explanations"


# ---------------------------------------------------------------------------
# _assemble_context_system_content — read-time injection ordering
# ---------------------------------------------------------------------------


def _make_ctx(**overrides):
    from app.voice.context import VoiceSessionContext

    defaults = dict(
        system_prompt="You are Aria.",
        skills_content=None,
        misc_notes="",
        lead_profile="",
        model="gpt-4o",
        temperature=0.7,
        max_tokens=300,
        tools=None,
        skills_index=None,
    )
    defaults.update(overrides)
    return VoiceSessionContext(**defaults)


def test_assembled_content_has_facts_block_after_lead_profile_before_skills():
    from app.voice.webhook import _assemble_context_system_content

    ctx = _make_ctx(
        lead_profile="[CONTEXTO DEL LEAD]\nname: Juan",
        profile_facts_block="--- Perfil acumulado ---\n- Ocupación: vendedor",
    )

    content = _assemble_context_system_content(
        ctx, loaded_skills={"my-skill": "Skill content here"}
    )

    lead_profile_idx = content.index("[CONTEXTO DEL LEAD]")
    facts_idx = content.index("--- Perfil acumulado ---")
    skill_idx = content.index("## Loaded Skill: my-skill")

    assert lead_profile_idx < facts_idx < skill_idx


def test_assembled_content_no_facts_block_when_empty():
    from app.voice.webhook import _assemble_context_system_content

    ctx = _make_ctx(
        lead_profile="[CONTEXTO DEL LEAD]\nname: Juan",
        profile_facts_block="",
    )

    content = _assemble_context_system_content(ctx)

    assert "Perfil acumulado" not in content
