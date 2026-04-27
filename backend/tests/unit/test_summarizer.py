"""Unit tests for the post-call summarizer (CAP-4 + Phase 5 structured outputs).

Covers:
- 0 turns → no GPT call, summary stays null
- GPT failure → logged, no exception raised, session stays completed
- do_not_call flag set when next_action_suggested = "do_not_call"
- Phase 5: parse() mode — full-axis extraction via PostCallAnalysis
- Phase 5: 0 turns → no GPT call (unchanged behavior)
- Phase 5: schema-violating response → caught, logged, non-fatal
- Phase 5: analysis axes flow through extracted_facts to Lead

Mocks _get_openai_client() — does NOT create Settings() or make real API calls.

TDD: RED → GREEN for Phase 5 tests (2.1 and 2.3).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_db(tmp_path: Path):
    """Isolated SQLite DB with quintana-seguros + one test lead."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/summarizer_test.db",
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
            name="Summary Lead",
            phone="+5411000003",
            lead_id="test-lead-sum-001",
        )
        await sess.commit()

    yield db_module

    await db_module.close_db()


async def _create_session(
    db_module, *, with_turns: list[tuple[str, str]] | None = None
) -> str:
    """Helper: create a CallSession (status=completed) with optional transcript turns."""
    from app.calls.service import create_session, add_transcript_turn

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        cs = await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id="test-lead-sum-001",
        )
        # Mark as completed so summarizer can find it
        cs.status = "completed"

        if with_turns:
            for role, content in with_turns:
                await add_transcript_turn(sess, cs.id, role, content)

        await sess.commit()
        return cs.id


def _make_parse_response(analysis_obj) -> MagicMock:
    """Create a mock OpenAI parse() response with a PostCallAnalysis Pydantic object."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.parsed = analysis_obj
    mock_response.choices[0].message.refusal = None
    return mock_response


def _make_mock_client(parse_return_value) -> AsyncMock:
    """Build a mock OpenAI client where .parse() returns parse_return_value."""
    mock_client = AsyncMock()
    mock_client.chat.completions.parse.return_value = parse_return_value
    return mock_client


def _make_full_analysis_payload():
    """Build a complete PostCallAnalysis instance for use in mocks."""
    from app.analysis_schema import (
        PostCallAnalysis,
        CallOutcome,
        DetectedInterests,
        IdentifiedProblem,
    )

    return PostCallAnalysis(
        summary="Lead was very interested in todo riesgo coverage for their Toyota.",
        objections=["price too high"],
        interest_level=85,
        current_insurance="La Caja",
        next_action_suggested="send_quote",
        misc_notes="Car make: Toyota",
        call_outcome=CallOutcome(
            classification="interested",
            reason="Lead explicitly requested a quote.",
            engagement_quality="high",
        ),
        detected_interests=DetectedInterests(
            products=["todo_riesgo"],
            specific_needs=["cobertura_amplia"],
            buying_signals=["asked about monthly price"],
        ),
        identified_problem=IdentifiedProblem(
            primary_need="Needs comprehensive vehicle coverage for new car.",
            pain_points=["no current insurance"],
            urgency="high",
        ),
    )


# ---------------------------------------------------------------------------
# CAP-4: 0 turns → no GPT call
# ---------------------------------------------------------------------------


async def test_summarizer_skips_when_no_turns(seeded_db):
    """generate_summary_and_facts() with 0 turns → no GPT call, session summary=None."""
    from app.summarizer import generate_summary_and_facts
    from app.calls.models import CallSession
    from sqlalchemy import select

    session_id = await _create_session(seeded_db, with_turns=None)

    mock_client = AsyncMock()
    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

        # OpenAI should NOT have been called at all
        mock_client.chat.completions.parse.assert_not_called()

    # Summary should remain null
    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(CallSession).where(CallSession.id == session_id)
        )
        cs = result.scalar_one()
        assert cs.summary is None


async def test_summarizer_skips_silently_no_exception(seeded_db):
    """generate_summary_and_facts() with 0 turns → does NOT raise any exception."""
    from app.summarizer import generate_summary_and_facts

    session_id = await _create_session(seeded_db, with_turns=None)

    mock_client = AsyncMock()
    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)  # no raise expected


# ---------------------------------------------------------------------------
# CAP-4: GPT failure → logged, no exception raised
# ---------------------------------------------------------------------------


async def test_summarizer_gpt_failure_no_exception(seeded_db):
    """GPT failure → logged, generate_summary_and_facts() does not raise."""
    from app.summarizer import generate_summary_and_facts

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("user", "Hola, me interesa un seguro"),
            ("agent", "Perfecto, te cuento..."),
        ],
    )

    mock_client = AsyncMock()
    mock_client.chat.completions.parse.side_effect = Exception("API timeout")

    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            # Must not raise
            await generate_summary_and_facts(session_id, db)
            await db.commit()


# ===========================================================================
# WARNING 1 — 6 scenarios without direct runtime tests (verify fix)
# ===========================================================================


async def test_call_analysis_upsert_retry_safe_same_session_id(seeded_db):
    """WARNING 1-A: Calling summarizer TWICE on the same session_id produces exactly ONE CallAnalysis row.

    This tests retry-safe upsert semantics: the second run must UPDATE the existing
    row rather than INSERT a duplicate (which would violate the UNIQUE constraint on session_id).
    """
    from app.summarizer import generate_summary_and_facts
    from app.calls.models import CallAnalysis
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "Hola, llamo de Quintana"),
            ("user", "Me interesa el todo riesgo"),
        ],
    )

    analysis = _make_full_analysis_payload()

    # --- First run ---
    mock_client_1 = _make_mock_client(_make_parse_response(analysis))
    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client_1, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    # --- Second run (retry / re-webhook) ---
    mock_client_2 = _make_mock_client(_make_parse_response(analysis))
    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client_2, "gpt-4o-mini")
    ):
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    # Exactly ONE row must exist (upsert, not duplicate insert)
    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(CallAnalysis).where(CallAnalysis.session_id == session_id)
        )
        rows = result.scalars().all()
        assert len(rows) == 1, (
            f"Expected exactly 1 CallAnalysis row after double summarizer run, "
            f"got {len(rows)}"
        )
        assert rows[0].analysis_status == "ok"


async def test_call_analysis_extra_axes_data_is_none_when_no_extra_axes(seeded_db):
    """WARNING 1-B: When the client has no extra_axes configured, extra_axes_data is NULL in CallAnalysis.

    The base path (no extra axes) must NOT write a dummy JSON value — it must be NULL.
    """
    from app.summarizer import generate_summary_and_facts
    from app.calls.models import CallAnalysis
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "Hola"),
            ("user", "Sí, me interesa"),
        ],
    )

    analysis = _make_full_analysis_payload()
    mock_client = _make_mock_client(_make_parse_response(analysis))

    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(CallAnalysis).where(CallAnalysis.session_id == session_id)
        )
        ca = result.scalar_one()
        # No extra axes configured → extra_axes_data must be NULL
        assert (
            ca.extra_axes_data is None
        ), "extra_axes_data must be NULL when no extra_axes are configured"


def test_extraction_config_deserialized_from_valid_spec_payload():
    """WARNING 1-C: ExtractionConfig.model_validate() correctly deserializes a spec-shaped JSON payload.

    Verifies round-trip: JSON dict → ExtractionConfig → fields match expected values.
    This is the deserialization path used by _load_extraction_config().
    """
    from app.analysis_schema import ExtractionConfig

    payload = {
        "disabled_axes": ["service_issues"],
        "extra_axes": [
            {
                "name": "property_type",
                "field_type": "str",
                "description": "Type of real estate property",
            }
        ],
        "prompt_addendum": "Focus on real estate in Buenos Aires.",
    }

    config = ExtractionConfig.model_validate(payload)

    assert config.disabled_axes == ["service_issues"]
    assert len(config.extra_axes) == 1
    assert config.extra_axes[0].name == "property_type"
    assert config.extra_axes[0].field_type == "str"
    assert config.extra_axes[0].description == "Type of real estate property"
    assert config.prompt_addendum == "Focus on real estate in Buenos Aires."


def test_build_system_prompt_fallback_to_analysis_system_prompt_when_config_none():
    """WARNING 1-D: build_system_prompt(None) returns ANALYSIS_SYSTEM_PROMPT exactly.

    This is the backward-compat fallback: when config=None, the deprecated static
    prompt is used (not the generic builder), ensuring legacy behavior is preserved.
    """
    from app.analysis_schema import build_system_prompt, ANALYSIS_SYSTEM_PROMPT

    result = build_system_prompt(None)

    assert result is ANALYSIS_SYSTEM_PROMPT, (
        "build_system_prompt(None) must return the exact ANALYSIS_SYSTEM_PROMPT object "
        "(identity check), not a generated version"
    )


async def test_call_analysis_extra_axes_data_round_trips_named_keys(seeded_db):
    """WARNING 1-E: extra_axes_data with named keys is stored and retrievable as JSON.

    When the LLM returns extra_axes_data with named keys, _upsert_call_analysis must
    serialize it to JSON and store it in the extra_axes_data column. On read-back,
    the JSON must deserialize to the same dict with the same keys.
    """
    import json
    from app.summarizer import _upsert_call_analysis
    from app.calls.models import CallAnalysis
    from sqlalchemy import select

    # Create a bare session (no turns needed — testing _upsert_call_analysis directly)
    assert seeded_db.async_session_factory is not None

    # We need a real session_id that exists in DB for the FK constraint
    session_id = await _create_session(
        seeded_db,
        with_turns=[("user", "test")],
    )

    extra_data = {"property_type": "apartment", "num_bedrooms": 3}
    facts = {
        "interest_level": 75,
        "next_action_suggested": "call_again",
        "current_insurance": None,
        "objections": [],
        "call_outcome": {
            "classification": "interested",
            "reason": "Lead interested in apartment.",
            "engagement_quality": "high",
        },
        "detected_interests": {
            "products": [],
            "specific_needs": [],
            "buying_signals": [],
        },
        "identified_problem": {
            "primary_need": "Apartment coverage.",
            "pain_points": [],
            "urgency": "medium",
        },
        "service_issues": {"issues": []},
        "profile_facts": {"facts": []},
        "commitment_signals": {"signals": []},
        "abandonment_reason": {"reason": None},
        "data_corrections": "",
        "misc_notes": "",
        "extra_axes_data": extra_data,
    }

    async with seeded_db.async_session_factory() as db:
        await _upsert_call_analysis(
            db,
            session_id=session_id,
            lead_id="test-lead-sum-001",
            client_id="quintana-seguros",
            summary="Test extra axes round-trip.",
            facts=facts,
        )
        await db.commit()

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(CallAnalysis).where(CallAnalysis.session_id == session_id)
        )
        ca = result.scalar_one()

        # extra_axes_data must be stored as JSON string
        assert ca.extra_axes_data is not None, "extra_axes_data must NOT be None"
        retrieved = json.loads(ca.extra_axes_data)
        assert retrieved["property_type"] == "apartment"
        assert retrieved["num_bedrooms"] == 3


async def test_call_analysis_upsert_no_duplicates_after_retry(seeded_db):
    """WARNING 1-F: After two summarizer runs, exactly one CallAnalysis row exists (no duplicates).

    This is a stricter variant of WARNING 1-A: verifies the DB count directly via
    a raw COUNT query rather than checking the ORM result list length, to catch
    any scenario where the uniqueness constraint might not be enforced in the ORM layer.
    """
    from app.summarizer import generate_summary_and_facts
    from app.calls.models import CallAnalysis
    from sqlalchemy import select, func

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "Buenos días"),
            ("user", "Me llamo Juan"),
        ],
    )

    analysis = _make_full_analysis_payload()

    for _ in range(2):
        mock_client = _make_mock_client(_make_parse_response(analysis))
        with patch(
            "app.summarizer._get_openai_client",
            return_value=(mock_client, "gpt-4o-mini"),
        ):
            assert seeded_db.async_session_factory is not None
            async with seeded_db.async_session_factory() as db:
                await generate_summary_and_facts(session_id, db)
                await db.commit()

    async with seeded_db.async_session_factory() as db:
        count_result = await db.execute(
            select(func.count()).where(CallAnalysis.session_id == session_id)
        )
        count = count_result.scalar_one()
        assert count == 1, (
            f"Expected exactly 1 CallAnalysis row after 2 summarizer runs, "
            f"got {count} — duplicate insert bug"
        )


async def test_summarizer_gpt_failure_session_stays_completed(seeded_db):
    """GPT failure → session status stays 'completed' (no rollback of session status)."""
    from app.summarizer import generate_summary_and_facts
    from app.calls.models import CallSession
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[("user", "Necesito un seguro")],
    )

    mock_client = AsyncMock()
    mock_client.chat.completions.parse.side_effect = Exception("Network error")

    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    # Session should still be completed
    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(CallSession).where(CallSession.id == session_id)
        )
        cs = result.scalar_one()
        assert cs.status == "completed"


# ---------------------------------------------------------------------------
# CAP-4: do_not_call flag
# ---------------------------------------------------------------------------


async def test_summarizer_sets_do_not_call_flag(seeded_db):
    """When next_action_suggested='do_not_call' → Lead.do_not_call is set to True."""
    from app.summarizer import generate_summary_and_facts
    from app.leads.models import Lead
    from app.analysis_schema import (
        PostCallAnalysis,
        CallOutcome,
        DetectedInterests,
        IdentifiedProblem,
    )
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "Hola, le llamo de Quintana Seguros"),
            ("user", "No me llamen más por favor"),
        ],
    )

    dnc_analysis = PostCallAnalysis(
        summary="El lead pidió no ser contactado más.",
        objections=["no quiere ser contactado"],
        interest_level=0,
        current_insurance=None,
        next_action_suggested="do_not_call",
        misc_notes="",
        call_outcome=CallOutcome(
            classification="hostile",
            reason="Lead explicitly asked not to be called again.",
            engagement_quality="low",
        ),
        detected_interests=DetectedInterests(),
        identified_problem=IdentifiedProblem(
            primary_need="No interest in insurance.",
            urgency="low",
        ),
    )

    mock_client = _make_mock_client(_make_parse_response(dnc_analysis))
    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    # Verify Lead.do_not_call is True
    async with seeded_db.async_session_factory() as db:
        result = await db.execute(select(Lead).where(Lead.id == "test-lead-sum-001"))
        lead = result.scalar_one()
        assert lead.do_not_call is True


async def test_summarizer_does_not_set_do_not_call_for_other_actions(seeded_db):
    """next_action_suggested='call_again' → Lead.do_not_call stays False."""
    from app.summarizer import generate_summary_and_facts
    from app.leads.models import Lead
    from app.analysis_schema import (
        PostCallAnalysis,
        CallOutcome,
        DetectedInterests,
        IdentifiedProblem,
    )
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "Hola, le llamo de Quintana Seguros"),
            ("user", "Me interesa, llámeme la semana que viene"),
        ],
    )

    call_again_analysis = PostCallAnalysis(
        summary="Lead interesado, prefiere ser contactado la próxima semana.",
        objections=[],
        interest_level=70,
        current_insurance=None,
        next_action_suggested="call_again",
        misc_notes="",
        call_outcome=CallOutcome(
            classification="follow_up",
            reason="Lead asked to be called back next week.",
            engagement_quality="medium",
        ),
        detected_interests=DetectedInterests(),
        identified_problem=IdentifiedProblem(
            primary_need="Interested in coverage but needs more time.",
            urgency="medium",
        ),
    )

    mock_client = _make_mock_client(_make_parse_response(call_again_analysis))
    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(select(Lead).where(Lead.id == "test-lead-sum-001"))
        lead = result.scalar_one()
        assert lead.do_not_call is False


async def test_summarizer_persists_summary_and_facts(seeded_db):
    """Successful GPT call → summary + extracted_facts persisted to CallSession."""
    from app.summarizer import generate_summary_and_facts
    from app.calls.models import CallSession
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "Hola"),
            ("user", "Sí, quiero cotizar"),
        ],
    )

    analysis = _make_full_analysis_payload()
    analysis.summary = "Lead interesado en cotización."
    analysis.interest_level = 80

    mock_client = _make_mock_client(_make_parse_response(analysis))
    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(CallSession).where(CallSession.id == session_id)
        )
        cs = result.scalar_one()
        assert cs.summary == "Lead interesado en cotización."
        assert cs.extracted_facts is not None
        assert cs.extracted_facts["interest_level"] == 80


# ---------------------------------------------------------------------------
# Phase 5 — 2.1 RED: Full-axis extraction via parse() mode
# ---------------------------------------------------------------------------


async def test_summarizer_extracts_call_outcome_axis(seeded_db):
    """Phase 5: extracted_facts contains call_outcome with all 3 subfields."""
    from app.summarizer import generate_summary_and_facts
    from app.calls.models import CallSession
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "Hola, llamo para ofrecerle un seguro"),
            ("user", "Sí, me interesa el todo riesgo"),
        ],
    )

    analysis = _make_full_analysis_payload()
    mock_client = _make_mock_client(_make_parse_response(analysis))

    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(CallSession).where(CallSession.id == session_id)
        )
        cs = result.scalar_one()
        assert cs.extracted_facts is not None
        assert "call_outcome" in cs.extracted_facts
        co = cs.extracted_facts["call_outcome"]
        assert co["classification"] == "interested"
        assert co["engagement_quality"] == "high"
        assert isinstance(co["reason"], str)
        assert len(co["reason"]) > 0


async def test_summarizer_extracts_detected_interests_axis(seeded_db):
    """Phase 5: extracted_facts contains detected_interests with products + needs."""
    from app.summarizer import generate_summary_and_facts
    from app.calls.models import CallSession
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "¿Qué tipo de cobertura le interesa?"),
            ("user", "Todo riesgo, y que sea económica"),
        ],
    )

    analysis = _make_full_analysis_payload()
    mock_client = _make_mock_client(_make_parse_response(analysis))

    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(CallSession).where(CallSession.id == session_id)
        )
        cs = result.scalar_one()
        assert "detected_interests" in cs.extracted_facts
        di = cs.extracted_facts["detected_interests"]
        assert "todo_riesgo" in di["products"]
        assert isinstance(di["specific_needs"], list)
        assert isinstance(di["buying_signals"], list)


async def test_summarizer_extracts_identified_problem_axis(seeded_db):
    """Phase 5: extracted_facts contains identified_problem with urgency."""
    from app.summarizer import generate_summary_and_facts
    from app.calls.models import CallSession
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "¿Actualmente tiene seguro?"),
            ("user", "No, el auto es nuevo y necesito cobertura urgente"),
        ],
    )

    analysis = _make_full_analysis_payload()
    mock_client = _make_mock_client(_make_parse_response(analysis))

    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(CallSession).where(CallSession.id == session_id)
        )
        cs = result.scalar_one()
        assert "identified_problem" in cs.extracted_facts
        ip = cs.extracted_facts["identified_problem"]
        assert isinstance(ip["primary_need"], str)
        assert len(ip["primary_need"]) > 0
        assert ip["urgency"] == "high"
        assert isinstance(ip["pain_points"], list)


async def test_summarizer_uses_parse_not_create(seeded_db):
    """Phase 5: summarizer calls .parse() not .create() for structured output."""
    from app.summarizer import generate_summary_and_facts

    session_id = await _create_session(
        seeded_db,
        with_turns=[("user", "Hola"), ("agent", "Hola, ¿en qué le puedo ayudar?")],
    )

    analysis = _make_full_analysis_payload()
    mock_client = _make_mock_client(_make_parse_response(analysis))

    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)

        # Must use parse(), NOT create()
        mock_client.chat.completions.parse.assert_called_once()
        mock_client.chat.completions.create.assert_not_called()


async def test_summarizer_uses_max_tokens_1024(seeded_db):
    """Phase 5: summarizer call uses max_tokens=1024."""
    from app.summarizer import generate_summary_and_facts

    session_id = await _create_session(
        seeded_db,
        with_turns=[("user", "Me interesa el todo riesgo")],
    )

    analysis = _make_full_analysis_payload()
    mock_client = _make_mock_client(_make_parse_response(analysis))

    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)

        call_kwargs = mock_client.chat.completions.parse.call_args[1]
        assert call_kwargs.get("max_tokens") == 1024


async def test_summarizer_uses_post_call_analysis_as_response_format(seeded_db):
    """Phase 5: summarizer passes PostCallAnalysis as response_format to parse()."""
    from app.summarizer import generate_summary_and_facts
    from app.analysis_schema import PostCallAnalysis

    session_id = await _create_session(
        seeded_db,
        with_turns=[("user", "Me interesa el seguro")],
    )

    analysis = _make_full_analysis_payload()
    mock_client = _make_mock_client(_make_parse_response(analysis))

    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)

        call_kwargs = mock_client.chat.completions.parse.call_args[1]
        assert call_kwargs.get("response_format") is PostCallAnalysis


# ---------------------------------------------------------------------------
# Phase 5 — 2.3 TRIANGULATE: schema-violating response + partial analysis logging
# ---------------------------------------------------------------------------


async def test_summarizer_refusal_response_is_non_fatal(seeded_db):
    """Phase 5: if parse() returns a refusal, summarizer logs and does NOT raise."""
    from app.summarizer import generate_summary_and_facts
    from app.calls.models import CallSession
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[("user", "Hola"), ("agent", "Hola")],
    )

    # Simulate a refusal: parsed is None, refusal has content
    mock_refusal_response = MagicMock()
    mock_refusal_response.choices = [MagicMock()]
    mock_refusal_response.choices[0].message.parsed = None
    mock_refusal_response.choices[0].message.refusal = "I cannot analyze this content."

    mock_client = AsyncMock()
    mock_client.chat.completions.parse.return_value = mock_refusal_response

    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            # Must not raise
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    # Session should remain completed (error was caught)
    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(CallSession).where(CallSession.id == session_id)
        )
        cs = result.scalar_one()
        assert cs.status == "completed"


async def test_summarizer_parse_exception_is_non_fatal(seeded_db):
    """Phase 5: if parse() raises an exception, summarizer logs and does NOT raise."""
    from app.summarizer import generate_summary_and_facts
    from app.calls.models import CallSession
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[("user", "Hola"), ("agent", "Hola")],
    )

    mock_client = AsyncMock()
    mock_client.chat.completions.parse.side_effect = ValueError(
        "Schema validation failed"
    )

    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            # Must not raise
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(CallSession).where(CallSession.id == session_id)
        )
        cs = result.scalar_one()
        assert cs.status == "completed"


# ---------------------------------------------------------------------------
# CRITICAL 1 — partial-analysis marker on LLM failure (verify fix)
# ---------------------------------------------------------------------------


async def test_summarizer_refusal_persists_partial_analysis_marker(seeded_db):
    """CRITICAL 1: LLM refusal → CallSession.extracted_facts gets a partial-analysis marker."""
    from app.summarizer import generate_summary_and_facts
    from app.calls.models import CallSession
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[("user", "Hola"), ("agent", "Buenos días")],
    )

    mock_refusal_response = MagicMock()
    mock_refusal_response.choices = [MagicMock()]
    mock_refusal_response.choices[0].message.parsed = None
    mock_refusal_response.choices[0].message.refusal = "I cannot analyze this content."

    mock_client = AsyncMock()
    mock_client.chat.completions.parse.return_value = mock_refusal_response

    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(CallSession).where(CallSession.id == session_id)
        )
        cs = result.scalar_one()
        # partial-analysis marker MUST be persisted
        assert cs.extracted_facts is not None
        assert cs.extracted_facts.get("_analysis_status") == "failed"
        assert "_analysis_error" in cs.extracted_facts
        assert "refus" in cs.extracted_facts["_analysis_error"].lower()


async def test_summarizer_parse_exception_persists_partial_analysis_marker(seeded_db):
    """CRITICAL 1: parse() exception → CallSession.extracted_facts gets a partial-analysis marker."""
    from app.summarizer import generate_summary_and_facts
    from app.calls.models import CallSession
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[("user", "Hola"), ("agent", "Buenos días")],
    )

    mock_client = AsyncMock()
    mock_client.chat.completions.parse.side_effect = ValueError(
        "Schema validation failed"
    )

    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(CallSession).where(CallSession.id == session_id)
        )
        cs = result.scalar_one()
        assert cs.extracted_facts is not None
        assert cs.extracted_facts.get("_analysis_status") == "failed"
        assert "_analysis_error" in cs.extracted_facts


# ---------------------------------------------------------------------------
# CRITICAL 2 — re-run overwrites existing analysis (verify fix)
# ---------------------------------------------------------------------------


async def test_summarizer_rerun_overwrites_old_analysis(seeded_db):
    """CRITICAL 2: running summarizer twice → second analysis overwrites the first."""
    from app.summarizer import generate_summary_and_facts
    from app.calls.models import CallSession
    from app.analysis_schema import (
        PostCallAnalysis,
        CallOutcome,
        DetectedInterests,
        IdentifiedProblem,
    )
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "Hola, llamo de Quintana Seguros"),
            ("user", "Sí, me interesa"),
        ],
    )

    # --- First run ---
    first_analysis = PostCallAnalysis(
        summary="First run summary.",
        objections=["precio"],
        interest_level=40,
        current_insurance=None,
        next_action_suggested="call_again",
        misc_notes="",
        call_outcome=CallOutcome(
            classification="follow_up",
            reason="Lead asked to call back.",
            engagement_quality="medium",
        ),
        detected_interests=DetectedInterests(products=["terceros"]),
        identified_problem=IdentifiedProblem(
            primary_need="Needs basic coverage.",
            urgency="low",
        ),
    )

    mock_client_first = _make_mock_client(_make_parse_response(first_analysis))
    with patch(
        "app.summarizer._get_openai_client",
        return_value=(mock_client_first, "gpt-4o-mini"),
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    # Verify first run persisted
    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(CallSession).where(CallSession.id == session_id)
        )
        cs = result.scalar_one()
        assert cs.summary == "First run summary."
        assert cs.extracted_facts["interest_level"] == 40

    # --- Second run (re-summarize, e.g. via webhook) ---
    second_analysis = PostCallAnalysis(
        summary="Second run summary — updated.",
        objections=["precio", "no time"],
        interest_level=85,
        current_insurance="La Caja",
        next_action_suggested="send_quote",
        misc_notes="Car: Toyota",
        call_outcome=CallOutcome(
            classification="interested",
            reason="Lead explicitly requested a quote on the second call.",
            engagement_quality="high",
        ),
        detected_interests=DetectedInterests(products=["todo_riesgo"]),
        identified_problem=IdentifiedProblem(
            primary_need="Needs comprehensive coverage for new car.",
            urgency="high",
        ),
    )

    mock_client_second = _make_mock_client(_make_parse_response(second_analysis))
    with patch(
        "app.summarizer._get_openai_client",
        return_value=(mock_client_second, "gpt-4o-mini"),
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    # Second run MUST overwrite
    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(CallSession).where(CallSession.id == session_id)
        )
        cs = result.scalar_one()
        assert cs.summary == "Second run summary — updated."
        assert cs.extracted_facts["interest_level"] == 85
        assert cs.extracted_facts["call_outcome"]["classification"] == "interested"
        assert "todo_riesgo" in cs.extracted_facts["detected_interests"]["products"]
        assert cs.extracted_facts["identified_problem"]["urgency"] == "high"


# ---------------------------------------------------------------------------
# CRITICAL 3 — unknown extra fields from LLM are ignored gracefully (verify fix)
# ---------------------------------------------------------------------------


async def test_summarizer_unknown_extra_fields_ignored(seeded_db):
    """CRITICAL 3: PostCallAnalysis ignores unknown fields from LLM without errors."""
    from app.analysis_schema import PostCallAnalysis

    # Simulate what happens when the LLM returns extra unknown fields.
    # With Pydantic v2 default mode (ignore), model_validate with extra fields
    # should NOT raise and should NOT include the extra fields in model_dump().
    raw_data = {
        "summary": "Test summary",
        "objections": [],
        "interest_level": 70,
        "current_insurance": None,
        "next_action_suggested": "call_again",
        "misc_notes": "",
        "call_outcome": {
            "classification": "interested",
            "reason": "Lead showed interest.",
            "engagement_quality": "high",
            # Extra unknown field from LLM:
            "unknown_llm_field": "some_value",
        },
        "detected_interests": {
            "products": ["todo_riesgo"],
            "specific_needs": [],
            "buying_signals": [],
        },
        "identified_problem": {
            "primary_need": "Needs coverage.",
            "pain_points": [],
            "urgency": "medium",
        },
        # Top-level unknown field:
        "extra_field_from_llm": "ignored_value",
        "another_unknown": 42,
    }

    # Should NOT raise — Pydantic v2 ignores extra fields by default
    analysis = PostCallAnalysis.model_validate(raw_data)

    # Core fields must be preserved correctly
    assert analysis.summary == "Test summary"
    assert analysis.interest_level == 70
    assert analysis.call_outcome.classification.value == "interested"
    assert "todo_riesgo" in analysis.detected_interests.products

    # Unknown fields must NOT appear in model_dump()
    dumped = analysis.model_dump()
    assert "extra_field_from_llm" not in dumped
    assert "another_unknown" not in dumped
    assert "unknown_llm_field" not in dumped.get("call_outcome", {})


# ---------------------------------------------------------------------------
# Issue #21 — Car correction propagation via data_corrections
# ---------------------------------------------------------------------------


def test_apply_data_corrections_updates_car_model():
    """_apply_data_corrections parses 'car_model: Polo Trend' and updates lead.car_model."""
    from app.summarizer import _apply_data_corrections
    from unittest.mock import MagicMock

    lead = MagicMock()
    lead.car_make = "VW"
    lead.car_model = "Golf"
    lead.car_year = 2019

    _apply_data_corrections(lead, "car_model: Polo Trend")

    assert (
        lead.car_model == "Polo Trend"
    ), "car_model must be updated to 'Polo Trend' from data_corrections"
    # car_make unchanged
    assert lead.car_make == "VW"


def test_apply_data_corrections_updates_car_make():
    """_apply_data_corrections parses 'car_make: Ford' and updates lead.car_make."""
    from app.summarizer import _apply_data_corrections
    from unittest.mock import MagicMock

    lead = MagicMock()
    lead.car_make = "VW"
    lead.car_model = "Golf"
    lead.car_year = 2019

    _apply_data_corrections(lead, "car_make: Ford")

    assert lead.car_make == "Ford"
    assert lead.car_model == "Golf"  # unchanged


def test_apply_data_corrections_leaves_columns_unchanged_when_no_match():
    """_apply_data_corrections with empty or irrelevant string leaves car columns unchanged."""
    from app.summarizer import _apply_data_corrections
    from unittest.mock import MagicMock

    lead = MagicMock()
    lead.car_make = "VW"
    lead.car_model = "Golf"
    lead.car_year = 2019

    # Empty string — no corrections
    _apply_data_corrections(lead, "")

    assert lead.car_make == "VW"
    assert lead.car_model == "Golf"
    assert lead.car_year == 2019


def test_apply_data_corrections_ignores_unrecognized_fields():
    """_apply_data_corrections with unrecognized field names does not crash or modify lead."""
    from app.summarizer import _apply_data_corrections
    from unittest.mock import MagicMock

    lead = MagicMock()
    lead.car_make = "VW"
    lead.car_model = "Golf"
    lead.car_year = 2019

    # Unknown field — should be silently ignored
    _apply_data_corrections(lead, "unknown_field: some value")

    assert lead.car_make == "VW"
    assert lead.car_model == "Golf"


def test_apply_data_corrections_multiple_lines():
    """_apply_data_corrections handles multiple corrections on separate lines."""
    from app.summarizer import _apply_data_corrections
    from unittest.mock import MagicMock

    lead = MagicMock()
    lead.car_make = "VW"
    lead.car_model = "Golf"
    lead.car_year = 2019

    _apply_data_corrections(lead, "car_make: Toyota\ncar_model: Corolla")

    assert lead.car_make == "Toyota"
    assert lead.car_model == "Corolla"


async def test_summarizer_analysis_axes_flow_to_lead(seeded_db):
    """Phase 5: analysis axes (call_outcome, etc.) are merged into Lead.extracted_facts."""
    from app.summarizer import generate_summary_and_facts
    from app.leads.models import Lead
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "Hola"),
            ("user", "Sí, me interesa mucho el todo riesgo"),
        ],
    )

    analysis = _make_full_analysis_payload()
    mock_client = _make_mock_client(_make_parse_response(analysis))

    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(select(Lead).where(Lead.id == "test-lead-sum-001"))
        lead = result.scalar_one()

        # Phase 5 axes should have flowed to Lead.extracted_facts
        assert lead.extracted_facts is not None
        assert "call_outcome" in lead.extracted_facts
        assert "detected_interests" in lead.extracted_facts
        assert "identified_problem" in lead.extracted_facts
        # Verify the values are correct
        assert lead.extracted_facts["call_outcome"]["classification"] == "interested"
        assert "todo_riesgo" in lead.extracted_facts["detected_interests"]["products"]
        assert lead.extracted_facts["identified_problem"]["urgency"] == "high"


# ===========================================================================
# Phase 3 — Dual-write: summarizer writes to new relational tables
# ===========================================================================


async def test_summarizer_dual_write_creates_call_analysis(seeded_db):
    """Phase 3: successful summarizer run creates a CallAnalysis row for the session."""
    from app.summarizer import generate_summary_and_facts
    from app.calls.models import CallAnalysis
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "Hola"),
            ("user", "Me interesa el todo riesgo"),
        ],
    )

    analysis = _make_full_analysis_payload()
    mock_client = _make_mock_client(_make_parse_response(analysis))

    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(CallAnalysis).where(CallAnalysis.session_id == session_id)
        )
        ca = result.scalar_one_or_none()
        assert ca is not None
        assert ca.lead_id == "test-lead-sum-001"
        assert ca.interest_level == 85
        assert ca.classification == "interested"
        assert ca.analysis_status == "ok"


async def test_summarizer_dual_write_creates_interest_history(seeded_db):
    """Phase 3: successful summarizer run creates a LeadInterestHistory row."""
    from app.summarizer import generate_summary_and_facts
    from app.leads.models import LeadInterestHistory
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "Hola"),
            ("user", "Quiero cotizar"),
        ],
    )

    analysis = _make_full_analysis_payload()
    mock_client = _make_mock_client(_make_parse_response(analysis))

    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(LeadInterestHistory).where(
                LeadInterestHistory.lead_id == "test-lead-sum-001"
            )
        )
        rows = result.scalars().all()
        assert len(rows) >= 1
        assert rows[-1].interest_level == 85
        assert rows[-1].source_call_id == session_id


async def test_summarizer_dual_write_creates_lead_profile_facts(seeded_db):
    """Phase 3: successful summarizer run creates LeadProfileFact rows for the lead."""
    from app.summarizer import generate_summary_and_facts
    from app.leads.models import LeadProfileFact
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "Hola"),
            ("user", "Tengo La Caja de seguro"),
        ],
    )

    analysis = _make_full_analysis_payload()
    mock_client = _make_mock_client(_make_parse_response(analysis))

    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(LeadProfileFact).where(
                LeadProfileFact.lead_id == "test-lead-sum-001"
            )
        )
        facts = result.scalars().all()
        assert len(facts) >= 1
        fact_keys = {f.fact_key for f in facts}
        # At minimum interest_level and current_insurance should be present
        assert "interest_level" in fact_keys or "current_insurance" in fact_keys


async def test_summarizer_dual_write_old_json_still_populated(seeded_db):
    """Phase 3: dual-write doesn't break old path — CallSession.extracted_facts stays populated."""
    from app.summarizer import generate_summary_and_facts
    from app.calls.models import CallSession
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "Hola"),
            ("user", "Sí, me interesa"),
        ],
    )

    analysis = _make_full_analysis_payload()
    mock_client = _make_mock_client(_make_parse_response(analysis))

    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(CallSession).where(CallSession.id == session_id)
        )
        cs = result.scalar_one()
        # Old path must still be populated (backward compat)
        assert cs.extracted_facts is not None
        assert cs.extracted_facts.get("interest_level") == 85
        assert (
            cs.summary
            == "Lead was very interested in todo riesgo coverage for their Toyota."
        )


async def test_summarizer_dual_write_gpt_failure_writes_call_analysis_failed(seeded_db):
    """Phase 3: GPT failure → CallAnalysis row with analysis_status='failed'."""
    from app.summarizer import generate_summary_and_facts
    from app.calls.models import CallAnalysis
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "Hola"),
            ("user", "Necesito un seguro"),
        ],
    )

    mock_client = AsyncMock()
    mock_client.chat.completions.parse.side_effect = Exception("API timeout")

    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(CallAnalysis).where(CallAnalysis.session_id == session_id)
        )
        ca = result.scalar_one_or_none()
        assert ca is not None
        assert ca.analysis_status == "failed"
        assert ca.analysis_error == "API timeout"


async def test_summarizer_dual_write_do_not_call_creates_fact_row(seeded_db):
    """Phase 3: do_not_call path → LeadProfileFact row with fact_key='do_not_call'."""
    from app.summarizer import generate_summary_and_facts
    from app.leads.models import LeadProfileFact, Lead
    from app.analysis_schema import (
        PostCallAnalysis,
        CallOutcome,
        DetectedInterests,
        IdentifiedProblem,
    )
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "Hola"),
            ("user", "No me llamen más por favor"),
        ],
    )

    dnc_analysis = PostCallAnalysis(
        summary="Lead no quiere ser contactado.",
        objections=["no quiere ser contactado"],
        interest_level=0,
        current_insurance=None,
        next_action_suggested="do_not_call",
        misc_notes="",
        call_outcome=CallOutcome(
            classification="hostile",
            reason="Lead asked not to be called.",
            engagement_quality="low",
        ),
        detected_interests=DetectedInterests(),
        identified_problem=IdentifiedProblem(
            primary_need="No interest.",
            urgency="low",
        ),
    )

    mock_client = _make_mock_client(_make_parse_response(dnc_analysis))
    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with seeded_db.async_session_factory() as db:
        # Old path: Lead.do_not_call must still be True (backward compat)
        result = await db.execute(select(Lead).where(Lead.id == "test-lead-sum-001"))
        lead = result.scalar_one()
        assert lead.do_not_call is True

        # New path: LeadProfileFact with do_not_call key
        result2 = await db.execute(
            select(LeadProfileFact).where(
                LeadProfileFact.lead_id == "test-lead-sum-001",
                LeadProfileFact.fact_key == "do_not_call",
            )
        )
        dnc_facts = result2.scalars().all()
        assert len(dnc_facts) >= 1
        assert dnc_facts[0].fact_value == "true"


async def test_summarizer_dual_write_no_session_without_lead(seeded_db):
    """Phase 3: session with no lead → CallAnalysis row exists but no LeadProfileFact rows."""
    from app.summarizer import generate_summary_and_facts
    from app.calls.models import CallAnalysis
    from app.leads.models import LeadProfileFact
    from app.calls.service import create_session
    from sqlalchemy import select

    # Create a session WITHOUT a lead_id
    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        cs = await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id=None,
        )
        cs.status = "completed"
        no_lead_session_id = cs.id
        from app.calls.service import add_transcript_turn

        await add_transcript_turn(sess, no_lead_session_id, "user", "Hola")
        await sess.commit()

    analysis = _make_full_analysis_payload()
    mock_client = _make_mock_client(_make_parse_response(analysis))

    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(no_lead_session_id, db)
            await db.commit()

    async with seeded_db.async_session_factory() as db:
        # CallAnalysis must exist for the session
        result = await db.execute(
            select(CallAnalysis).where(CallAnalysis.session_id == no_lead_session_id)
        )
        ca = result.scalar_one_or_none()
        assert ca is not None
        assert ca.lead_id is None

        # No LeadProfileFact rows with this source_call_id
        result2 = await db.execute(
            select(LeadProfileFact).where(
                LeadProfileFact.source_call_id == no_lead_session_id
            )
        )
        facts = result2.scalars().all()
        assert len(facts) == 0


# ===========================================================================
# FIX: CRITICAL 1 — Dual-write atomicity (Issue #34)
# ===========================================================================


async def test_summarizer_critical1_upsert_failure_rolls_back_legacy_writes(seeded_db):
    """CRITICAL 1: if _upsert_call_analysis raises, legacy summary/extracted_facts must NOT commit.

    This proves the full summarizer pipeline is wrapped in a single transactional boundary:
    if ANY new-table write fails, the entire transaction (including legacy fields) rolls back.
    """
    from app.summarizer import generate_summary_and_facts
    from app.calls.models import CallSession
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "Hola, llamo de Quintana Seguros"),
            ("user", "Me interesa un seguro todo riesgo"),
        ],
    )

    analysis = _make_full_analysis_payload()
    mock_client = _make_mock_client(_make_parse_response(analysis))

    with (
        patch(
            "app.summarizer._get_openai_client",
            return_value=(mock_client, "gpt-4o-mini"),
        ),
        patch(
            "app.summarizer._upsert_call_analysis",
            side_effect=RuntimeError("simulated new-table write failure"),
        ),
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    # If atomicity is correct: legacy fields must NOT have been written
    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(CallSession).where(CallSession.id == session_id)
        )
        cs = result.scalar_one()
        # The whole transaction must have rolled back: summary stays None
        assert cs.summary is None, (
            "CRITICAL 1 FAIL: legacy summary was committed even though "
            "_upsert_call_analysis raised — atomicity is broken"
        )
        # extracted_facts must also be None (not partially written)
        assert cs.extracted_facts is None, (
            "CRITICAL 1 FAIL: legacy extracted_facts was committed even though "
            "_upsert_call_analysis raised — atomicity is broken"
        )


# ===========================================================================
# FIX: CRITICAL 2 — data_corrections creates LeadProfileFact rows (Issue #34)
# ===========================================================================


async def test_summarizer_critical2_data_corrections_create_lead_profile_facts(
    seeded_db,
):
    """CRITICAL 2: data_corrections 'car_model: Polo' → LeadProfileFact row with fact_key='car_model'.

    After _apply_data_corrections() updates Lead columns, the dual-write path must
    also write LeadProfileFact rows for each correction (fact_key=field, confidence='high').
    """
    from app.summarizer import generate_summary_and_facts
    from app.leads.models import LeadProfileFact, Lead
    from app.analysis_schema import (
        PostCallAnalysis,
        CallOutcome,
        DetectedInterests,
        IdentifiedProblem,
    )
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "¿Qué auto tiene?"),
            ("user", "Tengo un Polo, modelo 2022"),
        ],
    )

    corrections_analysis = PostCallAnalysis(
        summary="Lead tiene un Polo 2022.",
        objections=[],
        interest_level=70,
        current_insurance=None,
        next_action_suggested="send_quote",
        misc_notes="",
        data_corrections="car_model: Polo\ncar_year: 2022",
        call_outcome=CallOutcome(
            classification="interested",
            reason="Lead provided car details.",
            engagement_quality="medium",
        ),
        detected_interests=DetectedInterests(),
        identified_problem=IdentifiedProblem(
            primary_need="Needs auto insurance.",
            urgency="medium",
        ),
    )

    mock_client = _make_mock_client(_make_parse_response(corrections_analysis))
    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with seeded_db.async_session_factory() as db:
        # Legacy path: Lead columns must be updated
        result = await db.execute(select(Lead).where(Lead.id == "test-lead-sum-001"))
        lead = result.scalar_one()
        assert lead.car_model == "Polo", "Legacy car_model column must be updated"
        assert lead.car_year == 2022, "Legacy car_year column must be updated"

        # New path: LeadProfileFact rows must exist for corrections
        result2 = await db.execute(
            select(LeadProfileFact).where(
                LeadProfileFact.lead_id == "test-lead-sum-001",
                LeadProfileFact.source_call_id == session_id,
                LeadProfileFact.fact_key == "car_model",
            )
        )
        car_model_facts = result2.scalars().all()
        assert (
            len(car_model_facts) >= 1
        ), "CRITICAL 2 FAIL: no LeadProfileFact row created for car_model correction"
        assert car_model_facts[0].fact_value == "Polo"

        result3 = await db.execute(
            select(LeadProfileFact).where(
                LeadProfileFact.lead_id == "test-lead-sum-001",
                LeadProfileFact.source_call_id == session_id,
                LeadProfileFact.fact_key == "car_year",
            )
        )
        car_year_facts = result3.scalars().all()
        assert (
            len(car_year_facts) >= 1
        ), "CRITICAL 2 FAIL: no LeadProfileFact row created for car_year correction"
        assert car_year_facts[0].fact_value == "2022"


# ===========================================================================
# Issue #35 — Phase 3: Persistence — 5 new CallAnalysis columns + Client config
# ===========================================================================


async def test_call_analysis_has_five_new_columns(seeded_db):
    """Phase 3: CallAnalysis row after summarizer run has the 5 new axis columns."""
    from app.summarizer import generate_summary_and_facts
    from app.calls.models import CallAnalysis
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "Hola"),
            ("user", "Hola, me interesa cotizar"),
        ],
    )

    analysis = _make_full_analysis_payload()
    mock_client = _make_mock_client(_make_parse_response(analysis))

    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(CallAnalysis).where(CallAnalysis.session_id == session_id)
        )
        ca = result.scalar_one_or_none()
        assert ca is not None

        # Verify 5 new columns exist on the ORM model
        assert hasattr(
            ca, "service_issues"
        ), "CallAnalysis must have service_issues column"
        assert hasattr(
            ca, "profile_facts"
        ), "CallAnalysis must have profile_facts column"
        assert hasattr(
            ca, "commitment_signals"
        ), "CallAnalysis must have commitment_signals column"
        assert hasattr(
            ca, "abandonment_reason"
        ), "CallAnalysis must have abandonment_reason column"
        assert hasattr(
            ca, "extra_axes_data"
        ), "CallAnalysis must have extra_axes_data column"


async def test_call_analysis_new_axes_persisted_from_summarizer(seeded_db):
    """Phase 3: Summarizer persists service_issues, profile_facts, commitment_signals, abandonment_reason."""
    from app.summarizer import generate_summary_and_facts
    from app.calls.models import CallAnalysis
    from app.analysis_schema import (
        PostCallAnalysis,
        CallOutcome,
        DetectedInterests,
        IdentifiedProblem,
        ServiceIssuesAxis,
        ProfileFactsAxis,
        CommitmentSignalsAxis,
        AbandonmentReasonAxis,
    )
    from sqlalchemy import select
    import json

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "¿Tuvo algún problema con el servicio anterior?"),
            ("user", "Sí, la atención fue muy mala"),
        ],
    )

    axes_analysis = PostCallAnalysis(
        summary="Lead con problemas de servicio anterior.",
        objections=["bad service"],
        interest_level=60,
        current_insurance="La Caja",
        next_action_suggested="send_quote",
        misc_notes="",
        call_outcome=CallOutcome(
            classification="interested",
            reason="Lead wants to switch provider.",
            engagement_quality="medium",
        ),
        detected_interests=DetectedInterests(products=["todo_riesgo"]),
        identified_problem=IdentifiedProblem(
            primary_need="Switch insurance provider.",
            urgency="medium",
        ),
        service_issues=ServiceIssuesAxis(
            issues=["poor customer service", "claim denied"]
        ),
        profile_facts=ProfileFactsAxis(facts=["owns a Fiat", "lives in Palermo"]),
        commitment_signals=CommitmentSignalsAxis(
            signals=["asked for quote comparison"]
        ),
        abandonment_reason=AbandonmentReasonAxis(reason=None),
    )

    mock_client = _make_mock_client(_make_parse_response(axes_analysis))
    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(CallAnalysis).where(CallAnalysis.session_id == session_id)
        )
        ca = result.scalar_one()

        # service_issues: stored as JSON text list
        issues = json.loads(ca.service_issues)
        assert "poor customer service" in issues
        assert "claim denied" in issues

        # profile_facts: stored as JSON text list
        facts = json.loads(ca.profile_facts)
        assert "owns a Fiat" in facts

        # commitment_signals: stored as JSON text list
        signals = json.loads(ca.commitment_signals)
        assert "asked for quote comparison" in signals

        # abandonment_reason: None → stored as NULL
        assert ca.abandonment_reason is None


async def test_call_analysis_abandonment_reason_persisted_when_set(seeded_db):
    """Phase 3: abandonment_reason is stored as text when the lead disengaged."""
    from app.summarizer import generate_summary_and_facts
    from app.calls.models import CallAnalysis
    from app.analysis_schema import (
        PostCallAnalysis,
        CallOutcome,
        DetectedInterests,
        IdentifiedProblem,
        AbandonmentReasonAxis,
        ServiceIssuesAxis,
        ProfileFactsAxis,
        CommitmentSignalsAxis,
    )
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "¿Le interesa?"),
            ("user", "No, ya conseguí algo mejor"),
        ],
    )

    abandon_analysis = PostCallAnalysis(
        summary="Lead encontró mejor oferta.",
        objections=["found cheaper"],
        interest_level=10,
        current_insurance=None,
        next_action_suggested="wait",
        misc_notes="",
        call_outcome=CallOutcome(
            classification="not_interested",
            reason="Lead found a cheaper competitor.",
            engagement_quality="low",
        ),
        detected_interests=DetectedInterests(),
        identified_problem=IdentifiedProblem(
            primary_need="Looking for cheapest option.",
            urgency="low",
        ),
        service_issues=ServiceIssuesAxis(),
        profile_facts=ProfileFactsAxis(),
        commitment_signals=CommitmentSignalsAxis(),
        abandonment_reason=AbandonmentReasonAxis(
            reason="Found a cheaper provider elsewhere"
        ),
    )

    mock_client = _make_mock_client(_make_parse_response(abandon_analysis))
    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(CallAnalysis).where(CallAnalysis.session_id == session_id)
        )
        ca = result.scalar_one()
        assert ca.abandonment_reason == "Found a cheaper provider elsewhere"


async def test_call_analysis_null_axes_on_failure(seeded_db):
    """Phase 3: Analysis failure marker — new axis columns remain at their defaults."""
    from app.summarizer import generate_summary_and_facts
    from app.calls.models import CallAnalysis
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[("user", "Hola"), ("agent", "Buenos días")],
    )

    mock_client = MagicMock()
    mock_client.chat.completions.parse = AsyncMock(side_effect=Exception("API error"))

    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(CallAnalysis).where(CallAnalysis.session_id == session_id)
        )
        ca = result.scalar_one()
        assert ca.analysis_status == "failed"
        # New columns should have their defaults (empty lists / null)
        assert ca.service_issues == "[]"
        assert ca.profile_facts == "[]"
        assert ca.commitment_signals == "[]"
        assert ca.abandonment_reason is None
        assert ca.extra_axes_data is None


async def test_client_extraction_config_column_nullable(seeded_db):
    """Phase 3: Client.extraction_config column is nullable — NULL for existing clients."""
    from app.tenants.models import Client
    from sqlalchemy import select

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(select(Client).where(Client.id == "quintana-seguros"))
        client = result.scalar_one()
        # extraction_config must exist as attribute and be NULL by default
        assert hasattr(
            client, "extraction_config"
        ), "Client must have extraction_config column"
        assert client.extraction_config is None


async def test_client_extraction_config_can_be_set(seeded_db):
    """Phase 3: Client.extraction_config can be stored as a JSON string."""
    import json
    from app.tenants.models import Client
    from sqlalchemy import select

    config_json = json.dumps(
        {"disabled_axes": [], "extra_axes": [], "prompt_addendum": ""}
    )

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(select(Client).where(Client.id == "quintana-seguros"))
        client = result.scalar_one()
        client.extraction_config = config_json
        await db.commit()

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(select(Client).where(Client.id == "quintana-seguros"))
        client = result.scalar_one()
        assert client.extraction_config == config_json
        parsed = json.loads(client.extraction_config)
        assert parsed["disabled_axes"] == []


# ===========================================================================
# Issue #35 — Phase 4: Config-aware summarizer pipeline
# ===========================================================================


async def test_call_gpt_summarize_null_config_uses_base_model(seeded_db):
    """Phase 4: _call_gpt_summarize(config=None) uses PostCallAnalysis as response_format."""
    from app.summarizer import generate_summary_and_facts
    from app.analysis_schema import PostCallAnalysis

    session_id = await _create_session(
        seeded_db,
        with_turns=[("user", "Me interesa el seguro")],
    )

    analysis = _make_full_analysis_payload()
    mock_client = _make_mock_client(_make_parse_response(analysis))

    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)

        call_kwargs = mock_client.chat.completions.parse.call_args[1]
        # NULL config (quintana-seguros has no extraction_config) → PostCallAnalysis
        assert call_kwargs.get("response_format") is PostCallAnalysis


async def test_call_gpt_summarize_with_config_uses_dynamic_model(seeded_db):
    """Phase 4: _call_gpt_summarize with config → uses build_analysis_model(config) as response_format."""
    import json
    from app.summarizer import generate_summary_and_facts
    from app.analysis_schema import build_analysis_model, ExtractionConfig
    from app.tenants.models import Client
    from sqlalchemy import select

    # Set extraction_config on the client
    config = ExtractionConfig(prompt_addendum="Real estate context")
    config_json = json.dumps(config.model_dump())

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(select(Client).where(Client.id == "quintana-seguros"))
        client = result.scalar_one()
        client.extraction_config = config_json
        await db.commit()

    session_id = await _create_session(
        seeded_db,
        with_turns=[("user", "Me interesa")],
    )

    analysis = _make_full_analysis_payload()
    mock_client = _make_mock_client(_make_parse_response(analysis))

    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)

        call_kwargs = mock_client.chat.completions.parse.call_args[1]
        used_format = call_kwargs.get("response_format")
        # Must NOT be the bare PostCallAnalysis class when config is set
        # (could be PostCallAnalysis itself if config is empty — that's also valid)
        expected_model = build_analysis_model(config)
        assert used_format is expected_model


async def test_call_gpt_summarize_with_config_uses_dynamic_prompt(seeded_db):
    """Phase 4: _call_gpt_summarize with config → system prompt is from build_system_prompt(config)."""
    import json
    from app.summarizer import generate_summary_and_facts
    from app.analysis_schema import ExtractionConfig
    from app.tenants.models import Client
    from sqlalchemy import select

    config = ExtractionConfig(prompt_addendum="Focus on real estate leads in CABA.")
    config_json = json.dumps(config.model_dump())

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(select(Client).where(Client.id == "quintana-seguros"))
        client = result.scalar_one()
        client.extraction_config = config_json
        await db.commit()

    session_id = await _create_session(
        seeded_db,
        with_turns=[("user", "Quiero ver propiedades")],
    )

    analysis = _make_full_analysis_payload()
    mock_client = _make_mock_client(_make_parse_response(analysis))

    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)

        call_kwargs = mock_client.chat.completions.parse.call_args[1]
        messages = call_kwargs.get("messages", [])
        system_message = next(
            (m["content"] for m in messages if m["role"] == "system"), None
        )
        assert system_message is not None
        # The system prompt must contain the addendum
        assert "Focus on real estate leads in CABA." in system_message


async def test_run_summarizer_null_config_no_error(seeded_db):
    """Phase 4: _run_summarizer() with NULL extraction_config does not error — uses base path."""
    from app.summarizer import generate_summary_and_facts
    from app.calls.models import CallAnalysis
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[("agent", "Hola"), ("user", "Sí, me interesa")],
    )

    analysis = _make_full_analysis_payload()
    mock_client = _make_mock_client(_make_parse_response(analysis))

    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            # quintana-seguros has extraction_config=NULL — must not raise
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(CallAnalysis).where(CallAnalysis.session_id == session_id)
        )
        ca = result.scalar_one()
        assert ca.analysis_status == "ok"


async def test_summarizer_gpt_refusal_with_config_is_non_fatal(seeded_db):
    """Phase 4: GPT refusal with dynamic model config → summarizer logs and does NOT raise."""
    import json
    from app.summarizer import generate_summary_and_facts
    from app.analysis_schema import ExtractionConfig
    from app.tenants.models import Client
    from sqlalchemy import select

    config = ExtractionConfig()
    config_json = json.dumps(config.model_dump())

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(select(Client).where(Client.id == "quintana-seguros"))
        client = result.scalar_one()
        client.extraction_config = config_json
        await db.commit()

    session_id = await _create_session(
        seeded_db,
        with_turns=[("user", "Hola"), ("agent", "Hola")],
    )

    mock_refusal_response = MagicMock()
    mock_refusal_response.choices = [MagicMock()]
    mock_refusal_response.choices[0].message.parsed = None
    mock_refusal_response.choices[0].message.refusal = "I cannot analyze this."

    mock_client = AsyncMock()
    mock_client.chat.completions.parse.return_value = mock_refusal_response

    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            # Must not raise
            await generate_summary_and_facts(session_id, db)
            await db.commit()


# ---------------------------------------------------------------------------
# Issue #36 — Phase 1: List-type LeadProfileFact accumulation
# ---------------------------------------------------------------------------


def _make_analysis_with_list_axes(
    *,
    profile_facts_list=None,
    pain_points=None,
    service_issues=None,
    commitment_signals=None,
    buying_signals=None,
):
    """Build a PostCallAnalysis with specific list-axis values."""
    from app.analysis_schema import (
        PostCallAnalysis,
        CallOutcome,
        DetectedInterests,
        IdentifiedProblem,
        ServiceIssuesAxis,
        ProfileFactsAxis,
        CommitmentSignalsAxis,
    )

    return PostCallAnalysis(
        summary="Test summary",
        interest_level=70,
        current_insurance="OSDE",
        next_action_suggested="send_quote",
        call_outcome=CallOutcome(
            classification="interested",
            reason="Lead was interested.",
            engagement_quality="high",
        ),
        detected_interests=DetectedInterests(
            products=[],
            specific_needs=[],
            buying_signals=buying_signals or [],
        ),
        identified_problem=IdentifiedProblem(
            primary_need="Needs insurance",
            pain_points=pain_points or [],
            urgency="medium",
        ),
        service_issues=ServiceIssuesAxis(issues=service_issues or []),
        profile_facts=ProfileFactsAxis(facts=profile_facts_list or []),
        commitment_signals=CommitmentSignalsAxis(signals=commitment_signals or []),
    )


@pytest.mark.asyncio
async def test_list_facts_first_insert_profile_facts(seeded_db):
    """Issue #36 Phase 1: First call with profile_facts inserts namespaced LeadProfileFact rows.

    GIVEN a lead with no existing LeadProfileFact rows for 'profile:' namespace
    WHEN _write_lead_profile_facts() runs with profile_facts.facts = ['owns a home', 'has 2 cars']
    THEN 2 rows are inserted: fact_key='profile:owns a home', fact_key='profile:has 2 cars', both active.
    """
    from app.summarizer import generate_summary_and_facts
    from app.leads.models import LeadProfileFact
    from sqlalchemy import select

    analysis = _make_analysis_with_list_axes(
        profile_facts_list=["owns a home", "has 2 cars"]
    )
    mock_client = _make_mock_client(_make_parse_response(analysis))

    session_id = await _create_session(
        seeded_db,
        with_turns=[("user", "Soy dueño de una casa"), ("agent", "Entendido")],
    )

    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(LeadProfileFact).where(
                LeadProfileFact.lead_id == "test-lead-sum-001",
                LeadProfileFact.fact_key.startswith("profile:"),
                LeadProfileFact.superseded_at == None,  # noqa: E711
            )
        )
        rows = list(result.scalars().all())

    profile_keys = {r.fact_key for r in rows}
    assert (
        "profile:owns a home" in profile_keys
    ), f"Expected profile:owns a home in {profile_keys}"
    assert (
        "profile:has 2 cars" in profile_keys
    ), f"Expected profile:has 2 cars in {profile_keys}"
    assert len([r for r in rows if r.fact_key.startswith("profile:")]) == 2


@pytest.mark.asyncio
async def test_list_facts_cross_call_dedup_no_duplicate_insert(seeded_db):
    """Issue #36 Phase 1: Second call with same item skips insert (cross-call dedup).

    GIVEN 'profile:owns a home' already exists as active row
    WHEN second call produces profile_facts = ['owns a home', 'retired']
    THEN 'profile:owns a home' is NOT re-inserted; 'profile:retired' IS inserted.
    """
    from app.summarizer import generate_summary_and_facts
    from app.leads.models import LeadProfileFact
    from sqlalchemy import select

    # First call — inserts 'owns a home'
    analysis1 = _make_analysis_with_list_axes(profile_facts_list=["owns a home"])
    mock_client1 = _make_mock_client(_make_parse_response(analysis1))
    session_id1 = await _create_session(
        seeded_db, with_turns=[("user", "Soy dueño de casa")]
    )
    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client1, "gpt-4o-mini")
    ):
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id1, db)
            await db.commit()

    # Second call — same 'owns a home' + new 'retired'
    analysis2 = _make_analysis_with_list_axes(
        profile_facts_list=["owns a home", "retired"]
    )
    mock_client2 = _make_mock_client(_make_parse_response(analysis2))
    session_id2 = await _create_session(
        seeded_db, with_turns=[("user", "Estoy jubilado")]
    )
    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client2, "gpt-4o-mini")
    ):
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id2, db)
            await db.commit()

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(LeadProfileFact).where(
                LeadProfileFact.lead_id == "test-lead-sum-001",
                LeadProfileFact.fact_key.startswith("profile:"),
                LeadProfileFact.superseded_at == None,  # noqa: E711
            )
        )
        rows = list(result.scalars().all())

    profile_keys = {r.fact_key for r in rows}
    # Exactly 2 active profile: rows (no duplicate for 'owns a home')
    assert profile_keys == {
        "profile:owns a home",
        "profile:retired",
    }, f"Expected exactly 2 profile: facts, got: {profile_keys}"


@pytest.mark.asyncio
async def test_list_facts_case_insensitive_dedup(seeded_db):
    """Issue #36 Phase 1: Deduplication is case-insensitive (normalized to lowercase).

    GIVEN 'pain:high premiums' exists as active row
    WHEN new call produces pain_points = ['High Premiums']
    THEN no new row is inserted (normalized key matches).
    """
    from app.summarizer import generate_summary_and_facts
    from app.leads.models import LeadProfileFact
    from sqlalchemy import select

    # First call — inserts 'pain:high premiums' (normalized)
    analysis1 = _make_analysis_with_list_axes(pain_points=["high premiums"])
    mock_client1 = _make_mock_client(_make_parse_response(analysis1))
    session_id1 = await _create_session(
        seeded_db, with_turns=[("user", "Las primas son altas")]
    )
    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client1, "gpt-4o-mini")
    ):
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id1, db)
            await db.commit()

    # Second call — same item but uppercase
    analysis2 = _make_analysis_with_list_axes(pain_points=["High Premiums"])
    mock_client2 = _make_mock_client(_make_parse_response(analysis2))
    session_id2 = await _create_session(
        seeded_db, with_turns=[("user", "Las primas son MUY altas")]
    )
    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client2, "gpt-4o-mini")
    ):
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id2, db)
            await db.commit()

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(LeadProfileFact).where(
                LeadProfileFact.lead_id == "test-lead-sum-001",
                LeadProfileFact.fact_key.startswith("pain:"),
                LeadProfileFact.superseded_at == None,  # noqa: E711
            )
        )
        rows = list(result.scalars().all())

    assert (
        len(rows) == 1
    ), f"Expected exactly 1 pain: row (dedup), got {len(rows)}: {[r.fact_key for r in rows]}"
    assert rows[0].fact_key == "pain:high premiums"


@pytest.mark.asyncio
async def test_list_facts_empty_list_skips_inserts(seeded_db):
    """Issue #36 Phase 1: Empty or None list-axis skips inserts.

    GIVEN pain_points = [] or None
    WHEN _write_lead_profile_facts() runs
    THEN no 'pain:' rows are created.
    """
    from app.summarizer import generate_summary_and_facts
    from app.leads.models import LeadProfileFact
    from sqlalchemy import select

    analysis = _make_analysis_with_list_axes(pain_points=[])
    mock_client = _make_mock_client(_make_parse_response(analysis))
    session_id = await _create_session(seeded_db, with_turns=[("user", "Todo bien")])
    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(LeadProfileFact).where(
                LeadProfileFact.lead_id == "test-lead-sum-001",
                LeadProfileFact.fact_key.startswith("pain:"),
            )
        )
        rows = list(result.scalars().all())

    assert len(rows) == 0, f"Expected 0 pain: rows for empty list, got {len(rows)}"


@pytest.mark.asyncio
async def test_list_facts_all_5_axes_persisted(seeded_db):
    """Issue #36 Phase 1: All 5 list axes are persisted with correct namespace prefixes.

    GIVEN a call analysis with non-empty values in all 5 list axes
    WHEN _write_lead_profile_facts() runs
    THEN rows are created with prefixes: profile:, pain:, service_issue:, signal:, buying_signal:
    """
    from app.summarizer import generate_summary_and_facts
    from app.leads.models import LeadProfileFact
    from sqlalchemy import select

    analysis = _make_analysis_with_list_axes(
        profile_facts_list=["married"],
        pain_points=["too expensive"],
        service_issues=["claim denied"],
        commitment_signals=["will call back tomorrow"],
        buying_signals=["asked for quote"],
    )
    mock_client = _make_mock_client(_make_parse_response(analysis))
    session_id = await _create_session(
        seeded_db, with_turns=[("user", "Quiero un seguro")]
    )
    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(LeadProfileFact).where(
                LeadProfileFact.lead_id == "test-lead-sum-001",
                LeadProfileFact.superseded_at == None,  # noqa: E711
            )
        )
        all_rows = list(result.scalars().all())

    # Extract by known prefixes
    by_prefix = {}
    for r in all_rows:
        prefix = r.fact_key.split(":")[0] + ":"
        by_prefix.setdefault(prefix, []).append(r.fact_key)

    assert (
        "profile:" in by_prefix
    ), f"Missing 'profile:' rows. Got prefixes: {list(by_prefix.keys())}"
    assert (
        "pain:" in by_prefix
    ), f"Missing 'pain:' rows. Got prefixes: {list(by_prefix.keys())}"
    assert (
        "service_issue:" in by_prefix
    ), f"Missing 'service_issue:' rows. Got prefixes: {list(by_prefix.keys())}"
    assert (
        "signal:" in by_prefix
    ), f"Missing 'signal:' rows. Got prefixes: {list(by_prefix.keys())}"
    assert (
        "buying_signal:" in by_prefix
    ), f"Missing 'buying_signal:' rows. Got prefixes: {list(by_prefix.keys())}"
