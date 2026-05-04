"""Integration tests for qora-profile-facts stateful pipeline.

Phase 5 — Integration + Regression Verification

Covers end-to-end scenarios for the profile facts pipeline:
- First-call: run_profile_facts_pipeline receives empty current_facts → only ADDs
- Second-call UPDATE: old fact is hard-deleted, new fact is inserted
- Second-call REMOVE: old fact is hard-deleted, disappears from memory context
- Deleted facts do NOT appear in build_memory_context()

Uses real DB (SQLite in-memory via tmp_path), mocked OpenAI client, and
real summarizer pipeline to verify the full flow.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock
import json

import pytest
import pytest_asyncio
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def profile_integration_db(tmp_path: Path):
    """Isolated SQLite DB with one test lead for profile facts integration tests."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/profile_integration.db",
    )
    await db_module.init_db(settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead

        await seed_quintana(sess)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Profile Integration Lead",
            phone="+5411099888",
            lead_id="lead-profile-integration-001",
        )
        await sess.commit()

    yield db_module

    await db_module.close_db()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_session_with_turns(db_module, *, turns: list[tuple[str, str]]) -> str:
    """Create a completed CallSession with the given transcript turns."""
    from app.calls.service import create_session, add_transcript_turn

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        cs = await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id="lead-profile-integration-001",
        )
        cs.status = "completed"
        for role, content in turns:
            await add_transcript_turn(sess, cs.id, role, content)
        await sess.commit()
        return cs.id


def _make_mock_analysis():
    """Build a minimal PostCallAnalysis for the mock client."""
    from app.analysis_schema import PostCallAnalysis, CallOutcome
    from app.analysis.universal.interest.interests import InterestsAxis
    from app.analysis.universal.objections import ObjectionsAxis

    return PostCallAnalysis(
        summary="Integration test summary.",
        objections=ObjectionsAxis(),
        interest_level=70,
        current_insurance=None,
        next_action_suggested="send_quote",
        # qora-misc-notes: misc_notes managed by standalone pipeline
        call_outcome=CallOutcome(
            classification="completed_positive",
            reason="Lead engaged.",
            confidence="medium",
        ),
        detected_interests=InterestsAxis(),
    )


def _make_mock_client_for_analysis(analysis):
    """Build a mock OpenAI client dispatching per-dimension parse() calls."""
    from app.analysis.universal import DIMENSION_MODULES
    from app.analysis.universal.interest.interests import InterestsAxis
    from app.analysis.universal.interest.interest_level import (
        InterestLevelResult,
        ProductScore,
    )

    schema_to_target = {
        mod.DIMENSION["schema"]: mod.DIMENSION["target_field"]
        for mod in DIMENSION_MODULES
    }

    mock_client = AsyncMock()

    async def _dispatch(*_args, response_format=None, **_kwargs):
        if response_format is InterestsAxis:
            axis_value = analysis.detected_interests
        elif response_format is InterestLevelResult:
            il = analysis.interest_level or 0
            axis_value = InterestLevelResult.model_construct(
                per_product=[
                    ProductScore.model_construct(
                        product="auto", score=il, reason="mock"
                    )
                ]
                if il > 0
                else [],
                general_score=il,
                level="medium",
                reason="Mock.",
                positive_signals=[],
                negative_signals=[],
                confidence="medium",
            )
        else:
            target_field = schema_to_target.get(response_format)
            if target_field is not None:
                axis_value = getattr(analysis, target_field)
            else:
                axis_value = analysis

        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.parsed = axis_value
        response.choices[0].message.refusal = None
        return response

    mock_client.beta.chat.completions.parse = AsyncMock(side_effect=_dispatch)
    mock_client.chat.completions.parse = mock_client.beta.chat.completions.parse
    mock_client.chat.completions.create = AsyncMock()
    return mock_client


async def _run_summarizer_with_profile_pipeline(db_module, session_id, profile_axis):
    """Run generate_summary_and_facts with a mocked OpenAI client + profile pipeline mock."""
    from app.summarizer import generate_summary_and_facts

    analysis = _make_mock_analysis()
    mock_client = _make_mock_client_for_analysis(analysis)

    async def _profile_mock(*_args, **_kwargs):
        return profile_axis

    assert db_module.async_session_factory is not None
    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        with patch(
            "app.summarizer.run_profile_facts_pipeline", side_effect=_profile_mock
        ):
            async with db_module.async_session_factory() as db:
                await generate_summary_and_facts(session_id, db)
                await db.commit()


# ---------------------------------------------------------------------------
# Integration test: first call → ADD operations only
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_profile_facts_first_call_add_inserts_rows(profile_integration_db):
    """Phase 5 integration: first-call ADD operations insert profile: rows with JSON fact_value.

    GIVEN a lead with no prior profile facts
    AND run_profile_facts_pipeline returns 2 ADD operations
    WHEN generate_summary_and_facts() runs
    THEN 2 LeadProfileFact rows with 'profile:' prefix are inserted
    AND fact_value is valid JSON with category, fact, evidence, confidence.
    """
    from app.analysis.universal.profile_facts import ProfileFactsAxis, ProfileFactUpdate
    from app.leads.models import LeadProfileFact
    from sqlalchemy import select

    session_id = await _create_session_with_turns(
        profile_integration_db,
        turns=[
            ("agent", "¿A qué se dedica?"),
            ("user", "Soy abogado y tengo 2 hijos"),
        ],
    )

    first_axis = ProfileFactsAxis(
        updates=[
            ProfileFactUpdate(
                operation="add",
                category="occupation",
                fact="abogado",
                evidence="Soy abogado",
                confidence="high",
                target_fact_id=None,
            ),
            ProfileFactUpdate(
                operation="add",
                category="family_context",
                fact="tiene 2 hijos",
                evidence="tengo 2 hijos",
                confidence="high",
                target_fact_id=None,
            ),
        ]
    )

    await _run_summarizer_with_profile_pipeline(
        profile_integration_db, session_id, first_axis
    )

    async with profile_integration_db.async_session_factory() as db:
        result = await db.execute(
            select(LeadProfileFact).where(
                LeadProfileFact.lead_id == "lead-profile-integration-001",
                LeadProfileFact.fact_key.startswith("profile:"),
                LeadProfileFact.superseded_at == None,  # noqa: E711
            )
        )
        rows = list(result.scalars().all())

    assert len(rows) == 2, (
        f"Expected 2 active profile: rows after first-call ADD, got {len(rows)}: "
        f"{[r.fact_key for r in rows]}"
    )

    fact_keys = {r.fact_key for r in rows}
    assert any(
        "occupation" in k for k in fact_keys
    ), f"Expected an 'occupation' profile fact key. Got: {fact_keys}"
    assert any(
        "family_context" in k for k in fact_keys
    ), f"Expected a 'family_context' profile fact key. Got: {fact_keys}"

    # Verify JSON structure
    for row in rows:
        value = json.loads(row.fact_value)
        assert "category" in value
        assert "fact" in value
        assert "evidence" in value
        assert "confidence" in value
        assert row.superseded_at is None, "New rows must NOT have superseded_at set"


# ---------------------------------------------------------------------------
# Integration test: second call UPDATE → hard delete old row, insert new
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_profile_facts_second_call_update_hard_deletes_and_inserts(
    profile_integration_db,
):
    """Phase 5 integration: second-call UPDATE hard-deletes old row, inserts new.

    Spec AD-3: UPDATE → DELETE old + INSERT new. NO superseded_at for profile: rows.

    GIVEN a lead with an existing 'profile:occupation:abogado' fact from call 1
    AND call 2's pipeline returns UPDATE targeting that fact
    WHEN generate_summary_and_facts() runs for call 2
    THEN the old row is completely gone (hard deleted, not superseded)
    AND a new row with the updated fact is inserted.
    """
    from app.analysis.universal.profile_facts import ProfileFactsAxis, ProfileFactUpdate
    from app.leads.models import LeadProfileFact
    from sqlalchemy import select

    # Call 1: insert initial occupation fact
    session_id_1 = await _create_session_with_turns(
        profile_integration_db,
        turns=[("agent", "¿Qué hace?"), ("user", "Soy abogado")],
    )
    first_axis = ProfileFactsAxis(
        updates=[
            ProfileFactUpdate(
                operation="add",
                category="occupation",
                fact="abogado",
                evidence="Soy abogado",
                confidence="high",
                target_fact_id=None,
            )
        ]
    )
    await _run_summarizer_with_profile_pipeline(
        profile_integration_db, session_id_1, first_axis
    )

    # Get the fact_key of the inserted row
    async with profile_integration_db.async_session_factory() as db:
        result = await db.execute(
            select(LeadProfileFact).where(
                LeadProfileFact.lead_id == "lead-profile-integration-001",
                LeadProfileFact.fact_key.startswith("profile:occupation:"),
            )
        )
        first_rows = list(result.scalars().all())
    assert len(first_rows) == 1, f"Expected 1 row after call 1, got {len(first_rows)}"
    old_fact_key = first_rows[0].fact_key
    old_row_id = first_rows[0].id

    # Call 2: UPDATE the occupation fact
    session_id_2 = await _create_session_with_turns(
        profile_integration_db,
        turns=[("agent", "¿Sigue siendo abogado?"), ("user", "Ahora soy juez")],
    )
    update_axis = ProfileFactsAxis(
        updates=[
            ProfileFactUpdate(
                operation="update",
                category="occupation",
                fact="juez",
                evidence="Ahora soy juez",
                confidence="high",
                target_fact_id=old_fact_key,
            )
        ]
    )
    await _run_summarizer_with_profile_pipeline(
        profile_integration_db, session_id_2, update_axis
    )

    async with profile_integration_db.async_session_factory() as db:
        # Old row must be GONE (hard deleted)
        old_result = await db.execute(
            select(LeadProfileFact).where(LeadProfileFact.id == old_row_id)
        )
        old_row = old_result.scalar_one_or_none()
        assert old_row is None, (
            "HARD DELETE: old profile fact row must not exist after UPDATE. "
            "Found it still in DB — superseded_at pattern is NOT allowed for profile: namespace."
        )

        # New row must exist
        new_result = await db.execute(
            select(LeadProfileFact).where(
                LeadProfileFact.lead_id == "lead-profile-integration-001",
                LeadProfileFact.fact_key.startswith("profile:occupation:"),
                LeadProfileFact.superseded_at == None,  # noqa: E711
            )
        )
        new_rows = list(new_result.scalars().all())
        assert (
            len(new_rows) == 1
        ), f"Expected exactly 1 active occupation fact after UPDATE, got {len(new_rows)}"
        new_val = json.loads(new_rows[0].fact_value)
        assert (
            new_val["fact"] == "juez"
        ), f"Updated fact must be 'juez', got: {new_val['fact']!r}"


# ---------------------------------------------------------------------------
# Integration test: REMOVE → fact disappears from memory context
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_profile_facts_remove_disappears_from_memory_context(
    profile_integration_db,
):
    """Phase 5 integration: REMOVE operation → fact disappears from build_memory_context().

    Spec: 'get_active_profile_facts() no longer returns it' after REMOVE.
    And by extension, build_memory_context() no longer includes it.

    GIVEN a lead with 'profile:lifestyle:runner' fact from call 1
    AND call 2 returns REMOVE for that fact
    WHEN build_memory_context() is called after call 2
    THEN the 'runner' fact does NOT appear in confirmed_facts.
    """
    from app.analysis.universal.profile_facts import ProfileFactsAxis, ProfileFactUpdate
    from app.leads.models import LeadProfileFact
    from app.leads.service import get_lead
    from app.memory import build_memory_context
    from sqlalchemy import select

    # Call 1: insert lifestyle fact
    session_id_1 = await _create_session_with_turns(
        profile_integration_db,
        turns=[("agent", "¿Hace deporte?"), ("user", "Sí, soy corredor")],
    )
    first_axis = ProfileFactsAxis(
        updates=[
            ProfileFactUpdate(
                operation="add",
                category="lifestyle",
                fact="corredor",
                evidence="Soy corredor",
                confidence="high",
                target_fact_id=None,
            )
        ]
    )
    await _run_summarizer_with_profile_pipeline(
        profile_integration_db, session_id_1, first_axis
    )

    # Verify the fact was inserted
    async with profile_integration_db.async_session_factory() as db:
        result = await db.execute(
            select(LeadProfileFact).where(
                LeadProfileFact.lead_id == "lead-profile-integration-001",
                LeadProfileFact.fact_key.startswith("profile:lifestyle:"),
                LeadProfileFact.superseded_at == None,  # noqa: E711
            )
        )
        first_rows = list(result.scalars().all())
    assert len(first_rows) == 1, f"Expected fact after call 1, got {len(first_rows)}"
    old_fact_key = first_rows[0].fact_key

    # Verify it appears in memory context after call 1
    async with profile_integration_db.async_session_factory() as db:
        lead = await get_lead(db, "lead-profile-integration-001")
        ctx = await build_memory_context(db, lead)
    assert "corredor" in ctx["confirmed_facts"], (
        "Expected 'corredor' to appear in memory context after call 1. "
        f"Got: {ctx['confirmed_facts']!r}"
    )

    # Call 2: REMOVE the lifestyle fact
    session_id_2 = await _create_session_with_turns(
        profile_integration_db,
        turns=[("agent", "¿Sigue corriendo?"), ("user", "No, me lesioné")],
    )
    remove_axis = ProfileFactsAxis(
        updates=[
            ProfileFactUpdate(
                operation="remove",
                category="lifestyle",
                fact="corredor",
                evidence="No, me lesioné — ya no corro",
                confidence="high",
                target_fact_id=old_fact_key,
            )
        ]
    )
    await _run_summarizer_with_profile_pipeline(
        profile_integration_db, session_id_2, remove_axis
    )

    # Verify the fact is GONE from memory context
    async with profile_integration_db.async_session_factory() as db:
        lead = await get_lead(db, "lead-profile-integration-001")
        ctx = await build_memory_context(db, lead)

    assert "corredor" not in ctx["confirmed_facts"], (
        "REMOVE: 'corredor' must NOT appear in memory context after REMOVE operation. "
        f"Got: {ctx['confirmed_facts']!r}"
    )
