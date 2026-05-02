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

import contextlib
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


def _axis_for_dimension(analysis_obj, target_field: str, schema_cls):
    """Build the per-dimension axis object (the ``.parsed`` value an analyze
    coroutine expects) from a full PostCallAnalysis payload.

    Simple axes (summary, ...) wrap a primitive field of PostCallAnalysis;
    complex axes (call_outcome, identified_problem, ...) are stored as-is.
    We look up the schema class to know which shape to return.

    qora-interest-pipeline: interest_level and detected_interests are NO LONGER
    in DIMENSION_MODULES. They are handled by run_interest_pipeline() in the
    summarizer. This helper only covers the 11 independent dimensions.
    """
    from app.analysis.universal import (
        AbandonmentReasonAxis,
        CommitmentsAxis,
        DataCorrectionsAxis,
        MiscNotesAxis,
        NextActionAxis,
        ObjectionsAxis,
        ProfileFactsAxis,
        ServiceIssuesAxis,
        SummaryAxis,
    )

    # Complex axes — the value already has the right shape.
    complex_targets = {
        "call_outcome",
        "identified_problem",
        "objections",          # qora-objections: now returns ObjectionsAxis directly
        "service_issues",
        "profile_facts",
        "commitments",
        "abandonment_reason",
    }
    if target_field in complex_targets:
        return getattr(analysis_obj, target_field)

    # Simple wrappers — pull the primitive out of the payload and wrap it.
    if schema_cls is SummaryAxis:
        return SummaryAxis(text=analysis_obj.summary)
    if schema_cls is ObjectionsAxis:
        # Fallback (should not reach here — objections is in complex_targets)
        return analysis_obj.objections
    if schema_cls is NextActionAxis:
        return NextActionAxis(action=str(analysis_obj.next_action_suggested))
    if schema_cls is MiscNotesAxis:
        return MiscNotesAxis(notes=str(analysis_obj.misc_notes or ""))
    if schema_cls is DataCorrectionsAxis:
        return DataCorrectionsAxis(
            corrections=str(getattr(analysis_obj, "data_corrections", "") or "")
        )
    if schema_cls is ServiceIssuesAxis:
        return ServiceIssuesAxis(issues=list(analysis_obj.service_issues.issues))
    if schema_cls is ProfileFactsAxis:
        return ProfileFactsAxis(facts=list(analysis_obj.profile_facts.facts))
    if schema_cls is CommitmentsAxis:
        return CommitmentsAxis(
            commitments=list(analysis_obj.commitments.commitments)
        )
    if schema_cls is AbandonmentReasonAxis:
        return AbandonmentReasonAxis(
            reason=getattr(analysis_obj.abandonment_reason, "reason", None)
        )
    raise AssertionError(f"Unknown axis schema: {schema_cls!r}")


def _make_parse_response(analysis_obj) -> MagicMock:
    """Compatibility shim — kept so existing tests reading ``.choices`` etc. work.

    Some tests use this directly with their own dispatch logic, so it still
    returns a MagicMock with the full payload as ``.parsed``. Most tests should
    use ``_make_mock_client(analysis_obj)`` which builds per-dimension responses.
    """
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.parsed = analysis_obj
    mock_response.choices[0].message.refusal = None
    return mock_response


def _make_mock_client(parse_return_value):
    """Build an AsyncOpenAI mock that dispatches per-dimension parse() calls.

    Accepts:
    - a full PostCallAnalysis instance, or
    - a pre-built MagicMock response whose ``choices[0].message.parsed`` is a
      PostCallAnalysis (legacy callers using ``_make_parse_response(analysis)``), or
    - any other pre-built response object (used by refusal tests where parsed
      is None — every dimension call returns the same mock so all 11 fail).

    qora-interest-pipeline: interest_level and detected_interests are handled by
    run_interest_pipeline (not by the mock client). The mock client covers the 11
    independent DIMENSION_MODULES. The pipeline mock is set up separately.
    """
    from app.analysis import PostCallAnalysis
    from app.analysis.universal import DIMENSION_MODULES

    analysis_obj = None
    if isinstance(parse_return_value, PostCallAnalysis):
        analysis_obj = parse_return_value
    else:
        try:
            candidate = parse_return_value.choices[0].message.parsed
        except Exception:
            candidate = None
        if isinstance(candidate, PostCallAnalysis):
            analysis_obj = candidate

    mock_client = AsyncMock()

    if analysis_obj is not None:
        schema_to_target = {
            mod.DIMENSION["schema"]: mod.DIMENSION["target_field"]
            for mod in DIMENSION_MODULES
        }

        # qora-interest-pipeline: also handle InterestsAxis and InterestLevelResult
        # so that run_interest_pipeline (called with mock_client) returns correct values.
        from app.analysis.universal.interest.interests import InterestsAxis
        from app.analysis.universal.interest.interest_level import InterestLevelResult

        async def _dispatch(*_args, response_format=None, **_kwargs):
            # Handle pipeline schemas directly
            if response_format is InterestsAxis:
                # Return the detected_interests from analysis_obj as InterestsAxis
                axis_value = analysis_obj.detected_interests
            elif response_format is InterestLevelResult:
                # Build an InterestLevelResult with per_product score matching analysis_obj.
                # IMPORTANT: interest_level.analyze() overrides general_score with the formula:
                # compute_general_score([ps.score for ps in per_product], previous=prev).
                # To get the desired interest_level, we put it as the single product score
                # and ensure compute_general_score returns the same value (100% current = max).
                il = analysis_obj.interest_level or 0
                from app.analysis.universal.interest.interest_level import ProductScore as _PS
                axis_value = InterestLevelResult.model_construct(
                    per_product=[
                        _PS.model_construct(
                            product="auto_todo_riesgo",
                            score=il,
                            reason="Mock product score.",
                        )
                    ] if il > 0 else [],
                    general_score=il,  # will be overridden by formula, but set for model_construct
                    level="high" if il >= 61 else "medium" if il >= 41 else "low",
                    reason="Mock.",
                    positive_signals=[],
                    negative_signals=[],
                    confidence="medium",
                )
            else:
                target_field = schema_to_target.get(response_format)
                if target_field is None:
                    axis_value = analysis_obj
                else:
                    axis_value = _axis_for_dimension(
                        analysis_obj, target_field, response_format
                    )
            response = MagicMock()
            response.choices = [MagicMock()]
            response.choices[0].message.parsed = axis_value
            response.choices[0].message.refusal = None
            return response

        mock_client.beta.chat.completions.parse = AsyncMock(side_effect=_dispatch)
    else:
        mock_client.beta.chat.completions.parse = AsyncMock(
            return_value=parse_return_value
        )

    # Mirror the legacy attribute path so older assertions on
    # ``mock_client.chat.completions.parse`` keep working.
    mock_client.chat.completions.parse = mock_client.beta.chat.completions.parse
    return mock_client


def _mock_run_interest_pipeline(analysis_obj):
    """Return an async mock for run_interest_pipeline that returns pipeline results.

    The pipeline returns (InterestsAxis|dict, InterestLevelResult|dict).
    We extract the values from the analysis_obj to simulate a successful pipeline run.
    """
    from app.analysis.universal.interest.interests import InterestsAxis
    from app.analysis.universal.interest.interest_level import InterestLevelResult

    interests_result = analysis_obj.detected_interests  # InterestsAxis
    interest_level = analysis_obj.interest_level  # int

    # Build a minimal InterestLevelResult for the pipeline mock
    level_result = InterestLevelResult.model_construct(
        per_product=[],
        general_score=interest_level,
        level="high" if interest_level >= 61 else "medium" if interest_level >= 41 else "low",
        reason="Mock interest level result.",
        positive_signals=[],
        negative_signals=[],
        confidence="medium",
    )

    async def _pipeline_mock(*_args, **_kwargs):
        return interests_result, level_result

    return _pipeline_mock


@contextlib.contextmanager
def _patch_summarizer(mock_client, analysis_obj=None):
    """Context manager that patches both _get_openai_client AND run_interest_pipeline.

    qora-interest-pipeline: the summarizer now calls run_interest_pipeline in addition
    to the 11 DIMENSION_MODULES. Tests must patch both to avoid real API calls.

    If analysis_obj is provided, run_interest_pipeline returns a successful tuple
    (interests_result, level_result). Otherwise uses a default empty pipeline result.
    """
    from app.analysis.universal.interest.interests import InterestsAxis
    from app.analysis.universal.interest.interest_level import InterestLevelResult

    if analysis_obj is not None:
        pipeline_mock = AsyncMock(side_effect=_mock_run_interest_pipeline(analysis_obj))
    else:
        # Default: empty pipeline result (no interests, interest_level=0)
        default_level = InterestLevelResult.model_construct(
            per_product=[],
            general_score=0,
            level="very_low",
            reason="No data.",
            positive_signals=[],
            negative_signals=[],
            confidence="low",
        )

        async def _default_pipeline(*_args, **_kwargs):
            return InterestsAxis(), default_level

        pipeline_mock = AsyncMock(side_effect=_default_pipeline)

    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ), patch(
        "app.summarizer.run_interest_pipeline", pipeline_mock
    ):
        yield


def _make_full_analysis_payload():
    """Build a complete PostCallAnalysis instance for use in mocks.

    qora-interest-pipeline: detected_interests now uses InterestsAxis (items: list[InterestItem])
    instead of old DetectedInterests (products/specific_needs/buying_signals).
    """
    from app.analysis_schema import (
        PostCallAnalysis,
        CallOutcome,
        IdentifiedProblem,
    )
    from app.analysis.universal.interest.interests import InterestsAxis, InterestItem
    from app.analysis.universal.objections import ObjectionsAxis, Objection

    return PostCallAnalysis(
        summary="Lead was very interested in todo riesgo coverage for their Toyota.",
        objections=ObjectionsAxis(objections=[
            Objection(
                category="price",
                strength="medium",
                resolution_status="unresolved",
                evidence="El precio es muy alto.",
                description="Price too high.",
                confidence="high",
            )
        ]),
        interest_level=85,
        current_insurance="La Caja",
        next_action_suggested="send_quote",
        misc_notes="Car make: Toyota",
        call_outcome=CallOutcome(
            classification="completed_positive",
            reason="Lead explicitly requested a quote.",
            confidence="high",
        ),
        detected_interests=InterestsAxis(items=[
            InterestItem(
                product="auto_todo_riesgo",
                needs=["precio_competitivo", "cobertura_amplia"],
                evidence="Me interesa el todo riesgo.",
                confidence="high",
            )
        ]),
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

    mock_client.beta.chat.completions.parse = mock_client.chat.completions.parse

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

    mock_client.beta.chat.completions.parse = mock_client.chat.completions.parse

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
        IdentifiedProblem,
    )
    from app.analysis.universal.interest.interests import InterestsAxis
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "Hola, le llamo de Quintana Seguros"),
            ("user", "No me llamen más por favor"),
        ],
    )

    from app.analysis.universal.objections import ObjectionsAxis as _OA
    dnc_analysis = PostCallAnalysis(
        summary="El lead pidió no ser contactado más.",
        objections=_OA(),
        interest_level=0,
        current_insurance=None,
        next_action_suggested="do_not_call",
        misc_notes="",
        call_outcome=CallOutcome(
            classification="hostile",
            reason="Lead explicitly asked not to be called again.",
            confidence="high",
        ),
        detected_interests=InterestsAxis(),
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


# ---------------------------------------------------------------------------
# qora-outcome: do_not_contact classification → lead.do_not_call = True
# ---------------------------------------------------------------------------


async def test_summarizer_do_not_contact_classification_sets_do_not_call(seeded_db):
    """qora-outcome spec: classification='do_not_contact' → lead.do_not_call = True."""
    from app.summarizer import generate_summary_and_facts
    from app.leads.models import Lead
    from app.analysis_schema import (
        PostCallAnalysis,
        CallOutcome,
        IdentifiedProblem,
    )
    from app.analysis.universal.interest.interests import InterestsAxis
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "Hola, llamo de Quintana Seguros"),
            ("user", "No me contacten nunca más"),
        ],
    )

    from app.analysis.universal.objections import ObjectionsAxis as _OA
    do_not_contact_analysis = PostCallAnalysis(
        summary="Lead pidió explícitamente no ser contactado.",
        objections=_OA(),
        interest_level=0,
        current_insurance=None,
        next_action_suggested="wait",  # NOT "do_not_call" — testing the classification path
        misc_notes="",
        call_outcome=CallOutcome(
            classification="do_not_contact",
            reason="Lead explicitly said do not contact.",
            confidence="high",
        ),
        detected_interests=InterestsAxis(),
        identified_problem=IdentifiedProblem(
            primary_need="No interest.",
            urgency="low",
        ),
    )

    mock_client = _make_mock_client(_make_parse_response(do_not_contact_analysis))
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
        assert lead.do_not_call is True, (
            "do_not_contact classification must set lead.do_not_call=True (qora-outcome spec)"
        )


async def test_summarizer_other_classification_does_not_set_do_not_call(seeded_db):
    """qora-outcome spec: non-do_not_contact classifications do NOT change lead.do_not_call."""
    from app.summarizer import generate_summary_and_facts
    from app.leads.models import Lead
    from app.analysis_schema import (
        PostCallAnalysis,
        CallOutcome,
        IdentifiedProblem,
    )
    from app.analysis.universal.interest.interests import InterestsAxis
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "Hola, llamo de Quintana Seguros"),
            ("user", "Me interesa, llámeme mañana"),
        ],
    )

    from app.analysis.universal.objections import ObjectionsAxis as _OA
    positive_analysis = PostCallAnalysis(
        summary="Lead interesado.",
        objections=_OA(),
        interest_level=80,
        current_insurance=None,
        next_action_suggested="call_again",
        misc_notes="",
        call_outcome=CallOutcome(
            classification="callback_requested",
            reason="Lead asked to be called tomorrow.",
            confidence="high",
        ),
        detected_interests=InterestsAxis(),
        identified_problem=IdentifiedProblem(
            primary_need="Needs auto insurance.",
            urgency="medium",
        ),
    )

    mock_client = _make_mock_client(_make_parse_response(positive_analysis))
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
        assert lead.do_not_call is False, (
            "Non-do_not_contact classification must NOT change lead.do_not_call"
        )


async def test_upsert_call_analysis_does_not_write_engagement_quality(seeded_db):
    """qora-outcome spec: _upsert_call_analysis must NOT write engagement_quality."""
    from app.summarizer import generate_summary_and_facts
    from app.calls.models import CallAnalysis
    from app.analysis_schema import (
        PostCallAnalysis,
        CallOutcome,
        IdentifiedProblem,
    )
    from app.analysis.universal.interest.interests import InterestsAxis
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "Hola"),
            ("user", "Quiero cotizar"),
        ],
    )

    from app.analysis.universal.objections import ObjectionsAxis as _OA
    analysis = PostCallAnalysis(
        summary="Lead quiere cotizar.",
        objections=_OA(),
        interest_level=75,
        current_insurance=None,
        next_action_suggested="send_quote",
        misc_notes="",
        call_outcome=CallOutcome(
            classification="completed_positive",
            reason="Lead requested quote.",
            confidence="high",
        ),
        detected_interests=InterestsAxis(),
        identified_problem=IdentifiedProblem(
            primary_need="Needs auto insurance.",
            urgency="medium",
        ),
    )

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
        assert ca.classification == "completed_positive"
        # engagement_quality column must NOT exist on CallAnalysis model
        assert not hasattr(ca, "engagement_quality"), (
            "CallAnalysis must NOT have engagement_quality column (qora-outcome spec)"
        )


async def test_summarizer_does_not_set_do_not_call_for_other_actions(seeded_db):
    """next_action_suggested='call_again' → Lead.do_not_call stays False."""
    from app.summarizer import generate_summary_and_facts
    from app.leads.models import Lead
    from app.analysis_schema import (
        PostCallAnalysis,
        CallOutcome,
        IdentifiedProblem,
    )
    from app.analysis.universal.interest.interests import InterestsAxis
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "Hola, le llamo de Quintana Seguros"),
            ("user", "Me interesa, llámeme la semana que viene"),
        ],
    )

    from app.analysis.universal.objections import ObjectionsAxis as _OA
    call_again_analysis = PostCallAnalysis(
        summary="Lead interesado, prefiere ser contactado la próxima semana.",
        objections=_OA(),
        interest_level=70,
        current_insurance=None,
        next_action_suggested="call_again",
        misc_notes="",
        call_outcome=CallOutcome(
            classification="callback_requested",
            reason="Lead asked to be called back next week.",
            confidence="medium",
        ),
        detected_interests=InterestsAxis(),
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
        assert co["classification"] == "completed_positive"
        assert "engagement_quality" not in co, (
            "engagement_quality must NOT be in call_outcome (qora-outcome spec)"
        )
        assert co["confidence"] in ("low", "medium", "high")
        assert isinstance(co["reason"], str)
        assert len(co["reason"]) > 0


async def test_summarizer_extracts_detected_interests_axis(seeded_db):
    """Phase 5: extracted_facts contains detected_interests with items format.

    qora-interest-pipeline: detected_interests now uses InterestsAxis (items: list[InterestItem])
    instead of old DetectedInterests (products/specific_needs/buying_signals).
    """
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
        # qora-interest-pipeline: detected_interests is now InterestsAxis format (items list)
        assert "items" in di
        assert isinstance(di["items"], list)
        # The mock has auto_todo_riesgo item
        assert len(di["items"]) >= 1
        products = [item["product"] for item in di["items"]]
        assert any("todo_riesgo" in p for p in products)


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
    """Phase 5: summarizer calls .parse() not .create() for structured output.

    qora-interest-pipeline: 11 dim calls + 2 pipeline calls (Agent1 + Agent2) = 13 total.
    """
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

        # Must use parse() (11 dim calls + 2 pipeline calls = 13), NOT create()
        from app.analysis.universal import DIMENSION_MODULES

        # 11 independent dims + 2 pipeline calls (Agent 1 InterestsAxis + Agent 2 InterestLevelResult)
        expected_parse_calls = len(DIMENSION_MODULES) + 2
        assert mock_client.chat.completions.parse.call_count == expected_parse_calls, (
            f"Expected {expected_parse_calls} parse() calls "
            f"(11 dims + 2 pipeline), got {mock_client.chat.completions.parse.call_count}"
        )
        mock_client.chat.completions.create.assert_not_called()


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

    mock_client.beta.chat.completions.parse = mock_client.chat.completions.parse

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
    mock_client.beta.chat.completions.parse = mock_client.chat.completions.parse

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

    mock_client.beta.chat.completions.parse = mock_client.chat.completions.parse

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
        # partial-analysis marker MUST be persisted. With per-dimension fan-out,
        # a refusal (parsed=None) causes every analyze() to raise on attribute
        # access, all 13 dimensions fail, and the summarizer raises RuntimeError.
        assert cs.extracted_facts is not None
        assert cs.extracted_facts.get("_analysis_status") == "failed"
        assert "_analysis_error" in cs.extracted_facts


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
    mock_client.beta.chat.completions.parse = mock_client.chat.completions.parse

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
        IdentifiedProblem,
    )
    from app.analysis.universal.interest.interests import InterestsAxis, InterestItem
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "Hola, llamo de Quintana Seguros"),
            ("user", "Sí, me interesa"),
        ],
    )

    from app.analysis.universal.objections import ObjectionsAxis as _OA
    # --- First run ---
    first_analysis = PostCallAnalysis(
        summary="First run summary.",
        objections=_OA(),
        interest_level=40,
        current_insurance=None,
        next_action_suggested="call_again",
        misc_notes="",
        call_outcome=CallOutcome(
            classification="callback_requested",
            reason="Lead asked to call back.",
            confidence="medium",
        ),
        detected_interests=InterestsAxis(items=[
            InterestItem(product="auto_terceros", needs=[], evidence="Me interesa terceros.", confidence="medium")
        ]),
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
        objections=_OA(),
        interest_level=85,
        current_insurance="La Caja",
        next_action_suggested="send_quote",
        misc_notes="Car: Toyota",
        call_outcome=CallOutcome(
            classification="completed_positive",
            reason="Lead explicitly requested a quote on the second call.",
            confidence="high",
        ),
        detected_interests=InterestsAxis(items=[
            InterestItem(product="auto_todo_riesgo", needs=[], evidence="Me interesa todo riesgo.", confidence="high")
        ]),
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
        # qora-interest-pipeline: interest_level is formula-computed (70/30 with previous)
        # first run stored 40, second run product score is 85 → formula: round(85*0.7 + 40*0.3) = 72
        assert cs.extracted_facts["interest_level"] > 40, (
            "Second run must produce a higher interest_level than the first run"
        )
        assert cs.extracted_facts["call_outcome"]["classification"] == "completed_positive"
        # qora-interest-pipeline: detected_interests uses items format
        di = cs.extracted_facts["detected_interests"]
        assert any("todo_riesgo" in item["product"] for item in di["items"])
        assert cs.extracted_facts["identified_problem"]["urgency"] == "high"


# ---------------------------------------------------------------------------
# CRITICAL 3 — unknown extra fields from LLM are ignored gracefully (verify fix)
# ---------------------------------------------------------------------------


async def test_summarizer_unknown_extra_fields_ignored(seeded_db):
    """CRITICAL 3: PostCallAnalysis ignores unknown fields from LLM without errors.

    qora-interest-pipeline: detected_interests now uses InterestsAxis (items format).
    """
    from app.analysis_schema import PostCallAnalysis

    # Simulate what happens when the LLM returns extra unknown fields.
    # With Pydantic v2 default mode (ignore), model_validate with extra fields
    # should NOT raise and should NOT include the extra fields in model_dump().
    raw_data = {
        "summary": "Test summary",
        "objections": {"objections": []},  # ObjectionsAxis dict format (qora-objections)
        "interest_level": 70,
        "current_insurance": None,
        "next_action_suggested": "call_again",
        "misc_notes": "",
        "call_outcome": {
            "classification": "completed_positive",
            "reason": "Lead showed interest.",
            "confidence": "high",
            # Extra unknown field from LLM:
            "unknown_llm_field": "some_value",
        },
        # qora-interest-pipeline: detected_interests uses InterestsAxis format
        "detected_interests": {
            "items": [
                {
                    "product": "auto_todo_riesgo",
                    "needs": [],
                    "evidence": "Me interesa.",
                    "confidence": "high",
                }
            ]
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
    assert analysis.call_outcome.classification == "completed_positive"
    # qora-interest-pipeline: detected_interests uses items format
    assert len(analysis.detected_interests.items) == 1
    assert analysis.detected_interests.items[0].product == "auto_todo_riesgo"

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
        assert lead.extracted_facts["call_outcome"]["classification"] == "completed_positive"
        # qora-interest-pipeline: detected_interests uses items format
        di = lead.extracted_facts["detected_interests"]
        assert any("todo_riesgo" in item["product"] for item in di["items"])
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
        assert ca.classification == "completed_positive"
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

    mock_client.beta.chat.completions.parse = mock_client.chat.completions.parse

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
        # With per-dimension fan-out, individual exceptions are logged per
        # dimension and the summarizer raises a synthetic RuntimeError when
        # ALL fail. The original error message is in the dimension logs.
        assert ca.analysis_error is not None
        assert "API timeout" in ca.analysis_error or "all 1" in ca.analysis_error


async def test_summarizer_dual_write_do_not_call_creates_fact_row(seeded_db):
    """Phase 3: do_not_call path → LeadProfileFact row with fact_key='do_not_call'."""
    from app.summarizer import generate_summary_and_facts
    from app.leads.models import LeadProfileFact, Lead
    from app.analysis_schema import (
        PostCallAnalysis,
        CallOutcome,
        IdentifiedProblem,
    )
    from app.analysis.universal.interest.interests import InterestsAxis
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "Hola"),
            ("user", "No me llamen más por favor"),
        ],
    )

    from app.analysis.universal.objections import ObjectionsAxis as _OA
    dnc_analysis = PostCallAnalysis(
        summary="Lead no quiere ser contactado.",
        objections=_OA(),
        interest_level=0,
        current_insurance=None,
        next_action_suggested="do_not_call",
        misc_notes="",
        call_outcome=CallOutcome(
            classification="hostile",
            reason="Lead asked not to be called.",
            confidence="high",
        ),
        detected_interests=InterestsAxis(),
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
        IdentifiedProblem,
    )
    from app.analysis.universal.interest.interests import InterestsAxis
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "¿Qué auto tiene?"),
            ("user", "Tengo un Polo, modelo 2022"),
        ],
    )

    from app.analysis.universal.objections import ObjectionsAxis as _OA
    corrections_analysis = PostCallAnalysis(
        summary="Lead tiene un Polo 2022.",
        objections=_OA(),
        interest_level=70,
        current_insurance=None,
        next_action_suggested="send_quote",
        misc_notes="",
        data_corrections="car_model: Polo\ncar_year: 2022",
        call_outcome=CallOutcome(
            classification="completed_neutral",
            reason="Lead provided car details.",
            confidence="medium",
        ),
        detected_interests=InterestsAxis(),
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
    """Phase 3: Summarizer persists service_issues (structured JSON), profile_facts, commitment_signals, abandonment_reason."""
    from app.summarizer import generate_summary_and_facts
    from app.calls.models import CallAnalysis
    from app.analysis_schema import (
        PostCallAnalysis,
        CallOutcome,
        IdentifiedProblem,
        ServiceIssuesAxis,
        ProfileFactsAxis,
        AbandonmentReasonAxis,
    )
    from app.analysis.universal.interest.interests import InterestsAxis, InterestItem
    from app.analysis.universal.commitments import CommitmentsAxis, Commitment
    from app.analysis.universal.service_issues import ServiceIssue
    from sqlalchemy import select
    import json

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "¿Tuvo algún problema con el servicio anterior?"),
            ("user", "Sí, la atención fue muy mala"),
        ],
    )

    from app.analysis.universal.objections import ObjectionsAxis as _OA
    axes_analysis = PostCallAnalysis(
        summary="Lead con problemas de servicio anterior.",
        objections=_OA(),
        interest_level=60,
        current_insurance="La Caja",
        next_action_suggested="send_quote",
        misc_notes="",
        call_outcome=CallOutcome(
            classification="completed_neutral",
            reason="Lead wants to switch provider.",
            confidence="medium",
        ),
        detected_interests=InterestsAxis(items=[
            InterestItem(product="auto_todo_riesgo", needs=[], evidence="Me interesa.", confidence="medium")
        ]),
        identified_problem=IdentifiedProblem(
            primary_need="Switch insurance provider.",
            urgency="medium",
        ),
        service_issues=ServiceIssuesAxis(
            issues=[
                ServiceIssue(
                    category="poor_attention",
                    description="Poor customer service from provider.",
                    source="current_provider",
                    severity="high",
                    evidence="La atención fue muy mala.",
                    confidence="high",
                ),
                ServiceIssue(
                    category="claim_problem",
                    description="Claim was denied without explanation.",
                    source="current_provider",
                    severity="high",
                    evidence="Me rechazaron el reclamo.",
                    confidence="high",
                ),
            ]
        ),
        profile_facts=ProfileFactsAxis(facts=["owns a Fiat", "lives in Palermo"]),
        commitments=CommitmentsAxis(
            commitments=[
                Commitment(
                    type="receive_quote",
                    owner="agent",
                    description="asked for quote comparison",
                    due="this_week",
                    strength="medium",
                    evidence="Me pidió una comparativa de cotizaciones.",
                    confidence="high",
                )
            ]
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

        # service_issues: stored as JSON array of objects (structured format)
        issues = json.loads(ca.service_issues)
        assert len(issues) == 2
        categories = {i["category"] for i in issues}
        assert "poor_attention" in categories
        assert "claim_problem" in categories

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
        IdentifiedProblem,
        AbandonmentReasonAxis,
        ServiceIssuesAxis,
        ProfileFactsAxis,
    )
    from app.analysis.universal.interest.interests import InterestsAxis
    from app.analysis.universal.commitments import CommitmentsAxis
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "¿Le interesa?"),
            ("user", "No, ya conseguí algo mejor"),
        ],
    )

    from app.analysis.universal.objections import ObjectionsAxis as _OA
    abandon_analysis = PostCallAnalysis(
        summary="Lead encontró mejor oferta.",
        objections=_OA(),
        interest_level=10,
        current_insurance=None,
        next_action_suggested="wait",
        misc_notes="",
        call_outcome=CallOutcome(
            classification="completed_negative",
            reason="Lead found a cheaper competitor.",
            confidence="high",
        ),
        detected_interests=InterestsAxis(),
        identified_problem=IdentifiedProblem(
            primary_need="Looking for cheapest option.",
            urgency="low",
        ),
        service_issues=ServiceIssuesAxis(),
        profile_facts=ProfileFactsAxis(),
        commitments=CommitmentsAxis(),
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

    mock_client.beta.chat.completions.parse = mock_client.chat.completions.parse

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


# ===========================================================================
# Issue #35 — Phase 4: Config-aware summarizer pipeline
# ===========================================================================


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
    """Build a PostCallAnalysis with specific list-axis values.

    service_issues accepts list[ServiceIssue] or list[str] (strings are
    coerced to ServiceIssue(category='other', description=str, ...) for
    backward-compatible test helpers).

    qora-interest-pipeline: detected_interests uses InterestsAxis (items format).
    buying_signals parameter is kept for backward compat but not stored in detected_interests.
    """
    from app.analysis_schema import (
        PostCallAnalysis,
        CallOutcome,
        IdentifiedProblem,
        ServiceIssuesAxis,
        ProfileFactsAxis,
    )
    from app.analysis.universal.interest.interests import InterestsAxis
    from app.analysis.universal.commitments import CommitmentsAxis, Commitment
    from app.analysis.universal.service_issues import ServiceIssue

    # Convert string descriptions to Commitment objects for the new structured API
    commitment_objects = [
        Commitment(
            type="other",
            owner="agent",
            description=desc,
            due="unknown",
            strength="medium",
            evidence=desc,
            confidence="medium",
        )
        for desc in (commitment_signals or [])
    ]

    # Convert plain strings to ServiceIssue objects for backward-compatible helpers
    raw_issues = service_issues or []
    issue_objects = [
        item
        if isinstance(item, ServiceIssue)
        else ServiceIssue(
            category="other",
            description=str(item),
            source="unknown",
            severity="medium",
            evidence=str(item),
            confidence="medium",
        )
        for item in raw_issues
    ]

    return PostCallAnalysis(
        summary="Test summary",
        interest_level=70,
        current_insurance="OSDE",
        next_action_suggested="send_quote",
        call_outcome=CallOutcome(
            classification="completed_positive",
            reason="Lead was interested.",
            confidence="high",
        ),
        # qora-interest-pipeline: use InterestsAxis (items format)
        detected_interests=InterestsAxis(),
        identified_problem=IdentifiedProblem(
            primary_need="Needs insurance",
            pain_points=pain_points or [],
            urgency="medium",
        ),
        service_issues=ServiceIssuesAxis(issues=issue_objects),
        profile_facts=ProfileFactsAxis(facts=profile_facts_list or []),
        commitments=CommitmentsAxis(commitments=commitment_objects),
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
    """Issue #36 Phase 1: The 4 active list axes are persisted with correct namespace prefixes.

    qora-interest-pipeline: buying_signal: namespace is now empty because buying_signals
    was removed from InterestsAxis. The 4 remaining axes (profile:, pain:, service_issue:,
    signal:) are still persisted as before.

    GIVEN a call analysis with non-empty values in profile_facts, pain_points, service_issues, commitments
    WHEN _write_lead_profile_facts() runs
    THEN rows are created with prefixes: profile:, pain:, service_issue:, signal:
    AND no buying_signal: rows are created (buying_signals no longer in detected_interests)
    """
    from app.summarizer import generate_summary_and_facts
    from app.leads.models import LeadProfileFact
    from sqlalchemy import select

    analysis = _make_analysis_with_list_axes(
        profile_facts_list=["married"],
        pain_points=["too expensive"],
        service_issues=["claim denied"],
        commitment_signals=["will call back tomorrow"],
        buying_signals=["asked for quote"],  # kept for compat but NOT stored anymore
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
    # qora-interest-pipeline: buying_signal: is no longer populated (removed from InterestsAxis)
    assert "buying_signal:" not in by_prefix, (
        "buying_signal: rows must NOT be created (buying_signals removed from InterestsAxis)"
    )


# ===========================================================================
# qora-objections Phase 3 — Structured objections integration
# ===========================================================================


def test_merge_facts_into_lead_extracts_category_from_ObjectionsAxis():
    """_merge_facts_into_lead: structured ObjectionsAxis → lead.objections_heard gets flat categories.

    Site 1: When facts['objections'] is a model_dump() of ObjectionsAxis,
    lead.objections_heard must receive the category strings, NOT dicts.
    """
    from app.summarizer import _merge_facts_into_lead
    from unittest.mock import MagicMock, AsyncMock, patch
    from app.analysis.universal.objections import ObjectionsAxis, Objection

    axis = ObjectionsAxis(objections=[
        Objection(
            category="price",
            strength="high",
            resolution_status="unresolved",
            evidence="El precio es muy alto.",
            description="Price objection.",
            confidence="high",
        ),
        Objection(
            category="trust",
            strength="medium",
            resolution_status="unresolved",
            evidence="No confío en la empresa.",
            description="Trust objection.",
            confidence="medium",
        ),
    ])
    # facts is the model_dump() output of PostCallAnalysis
    facts = {"objections": axis.model_dump()}

    lead = MagicMock()
    lead.objections_heard = None
    lead.extracted_facts = None

    import asyncio

    async def run():
        with patch("app.summarizer._write_lead_profile_facts", new_callable=AsyncMock):
            with patch("app.summarizer._write_interest_history"):
                with patch("app.summarizer._write_correction_facts", new_callable=AsyncMock):
                    from sqlalchemy.ext.asyncio import AsyncSession
                    db = AsyncMock(spec=AsyncSession)
                    with patch("sqlalchemy.future.select"), patch("app.summarizer.select") as mock_select:
                        mock_select.return_value = MagicMock()
                        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=lead)))
                        await _merge_facts_into_lead(db, "lead-id", "summary", facts)

    asyncio.get_event_loop().run_until_complete(run())

    # lead.objections_heard must contain flat category strings
    assert lead.objections_heard is not None
    assert "price" in lead.objections_heard, (
        "lead.objections_heard must contain 'price' category string"
    )
    assert "trust" in lead.objections_heard, (
        "lead.objections_heard must contain 'trust' category string"
    )
    # Must NOT contain dicts
    for item in lead.objections_heard:
        assert isinstance(item, str), (
            f"lead.objections_heard items must be strings, got: {type(item)}"
        )


def test_upsert_call_analysis_stores_objections_as_structured_json():
    """_upsert_call_analysis: ObjectionsAxis.model_dump()['objections'] → JSON array of dicts.

    Site 2: ca.objections must be serialized structured dicts, NOT flat strings.
    """
    from app.summarizer import _to_json_list
    from app.analysis.universal.objections import ObjectionsAxis, Objection
    import json

    axis = ObjectionsAxis(objections=[
        Objection(
            category="timing",
            strength="low",
            resolution_status="resolved",
            evidence="No tengo tiempo ahora.",
            description="Timing objection.",
            confidence="medium",
        ),
    ])
    # Simulate what upsert does with the structured axis
    raw = (axis.model_dump() or {}).get("objections")
    result = _to_json_list(raw)
    parsed = json.loads(result)

    assert len(parsed) == 1
    assert isinstance(parsed[0], dict), "Each objection must be serialized as dict"
    assert parsed[0]["category"] == "timing"
    assert "strength" in parsed[0]
    assert "resolution_status" in parsed[0]


@pytest.mark.asyncio
async def test_write_lead_profile_facts_creates_objection_namespace_rows(seeded_db):
    """_write_lead_profile_facts: ObjectionsAxis → 'objection:' namespace LeadProfileFact rows.

    Site 3: _LIST_AXES must include ('objection:', ...) following the service_issue pattern.
    """
    from app.summarizer import generate_summary_and_facts
    from app.leads.models import LeadProfileFact
    from app.analysis.universal.objections import ObjectionsAxis, Objection
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "¿Tiene alguna objeción?"),
            ("user", "El precio es muy alto y no confío en la cobertura"),
        ],
    )

    from app.analysis_schema import (
        PostCallAnalysis,
        CallOutcome,
        IdentifiedProblem,
    )
    from app.analysis.universal.interest.interests import InterestsAxis

    axis = ObjectionsAxis(objections=[
        Objection(
            category="price",
            strength="high",
            resolution_status="unresolved",
            evidence="El precio es muy alto.",
            description="Price objection.",
            confidence="high",
        ),
        Objection(
            category="trust",
            strength="medium",
            resolution_status="unresolved",
            evidence="No confío en la cobertura.",
            description="Trust objection.",
            confidence="medium",
        ),
    ])

    objections_analysis = PostCallAnalysis(
        summary="Lead has price and trust objections.",
        objections=axis,
        interest_level=40,
        current_insurance=None,
        next_action_suggested="call_again",
        misc_notes="",
        call_outcome=CallOutcome(
            classification="completed_neutral",
            reason="Lead not ready yet.",
            confidence="medium",
        ),
        detected_interests=InterestsAxis(),
        identified_problem=IdentifiedProblem(
            primary_need="Needs cheaper coverage.",
            urgency="medium",
        ),
    )

    mock_client = _make_mock_client(_make_parse_response(objections_analysis))
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
                LeadProfileFact.lead_id == "test-lead-sum-001",
                LeadProfileFact.fact_key.startswith("objection:"),
                LeadProfileFact.superseded_at == None,  # noqa: E711
            )
        )
        rows = list(result.scalars().all())

    objection_keys = {r.fact_key for r in rows}
    assert "objection:price" in objection_keys, (
        f"Expected 'objection:price' LeadProfileFact row. Got: {objection_keys}"
    )
    assert "objection:trust" in objection_keys, (
        f"Expected 'objection:trust' LeadProfileFact row. Got: {objection_keys}"
    )
