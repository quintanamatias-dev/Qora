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
