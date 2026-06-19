"""Integration tests for the data corrections pipeline in the summarizer flow.

Tasks 4.2 and 4.3: Pipeline called inside _merge_facts_into_lead savepoint,
corrections stored in facts["data_corrections"] for audit, email/age columns.

TDD: RED → GREEN → TRIANGULATE → REFACTOR
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
async def corr_db(tmp_path: Path):
    """Isolated SQLite DB with quintana-seguros + one test lead."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/corr_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations
    await _init_db_with_migrations(db_module, settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead

        await seed_quintana(sess)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Carlos Lopez",
            phone="+5411000050",
            lead_id="corr-lead-001",
        )
        await sess.commit()

    yield db_module
    await db_module.close_db()


async def _make_session(db_module, *, turns):
    from app.calls.service import create_session, add_transcript_turn

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        cs = await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id="corr-lead-001",
        )
        cs.status = "completed"
        for role, content in turns:
            await add_transcript_turn(sess, cs.id, role, content)
        await sess.commit()
        return cs.id


def _base_mock_client(analysis_obj):
    """Build a mock client that handles all pipeline schemas."""
    from app.analysis.universal import DIMENSION_MODULES
    from app.analysis.universal.interest.interests import InterestsAxis
    from app.analysis.universal.interest.interest_level import InterestLevelResult
    from app.analysis.universal.data_corrections import DataCorrectionsAxis as _DCA

    schema_to_target = {
        mod.DIMENSION["schema"]: mod.DIMENSION["target_field"]
        for mod in DIMENSION_MODULES
    }

    from tests.unit.test_summarizer import _axis_for_dimension

    async def _dispatch(*_args, response_format=None, **_kwargs):
        if response_format is _DCA:
            return _mock_response(_DCA(corrections=[]))
        if response_format is InterestsAxis:
            return _mock_response(analysis_obj.detected_interests)
        if response_format is InterestLevelResult:
            il = analysis_obj.interest_level or 0
            from app.analysis.universal.interest.interest_level import (
                ProductScore as _PS,
            )

            axis_value = InterestLevelResult.model_construct(
                per_product=[
                    _PS.model_construct(
                        product="auto_todo_riesgo", score=il, reason="M."
                    )
                ]
                if il > 0
                else [],
                general_score=il,
                level="high" if il >= 61 else "medium" if il >= 41 else "low",
                reason="Mock.",
                positive_signals=[],
                negative_signals=[],
                confidence="medium",
            )
            return _mock_response(axis_value)
        target_field = schema_to_target.get(response_format)
        if target_field is None:
            axis_value = analysis_obj
        else:
            axis_value = _axis_for_dimension(
                analysis_obj, target_field, response_format
            )
        return _mock_response(axis_value)

    mock_client = AsyncMock()
    mock_client.beta.chat.completions.parse = AsyncMock(side_effect=_dispatch)
    mock_client.chat.completions.parse = mock_client.beta.chat.completions.parse
    return mock_client


def _mock_response(parsed_value):
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.parsed = parsed_value
    resp.choices[0].message.refusal = None
    return resp


def _base_analysis():
    from app.analysis_schema import PostCallAnalysis, CallOutcome, IdentifiedProblem
    from app.analysis.universal.interest.interests import InterestsAxis
    from app.analysis.universal.objections import ObjectionsAxis

    return PostCallAnalysis(
        summary="Test call.",
        objections=ObjectionsAxis(),
        interest_level=70,
        current_insurance=None,
        next_action_suggested="call_again",
        call_outcome=CallOutcome(
            classification="completed_neutral",
            reason="Test.",
            confidence="medium",
        ),
        detected_interests=InterestsAxis(),
        identified_problem=IdentifiedProblem(
            primary_need="Test.",
            urgency="low",
        ),
    )


# ---------------------------------------------------------------------------
# 4.2 — Pipeline called inside _merge_facts_into_lead savepoint
# ---------------------------------------------------------------------------


async def test_pipeline_called_when_lead_id_present(corr_db):
    """When lead_id is present, run_data_corrections_pipeline MUST be called once."""
    from app.summarizer import generate_summary_and_facts

    session_id = await _make_session(
        corr_db,
        turns=[("agent", "Hola"), ("user", "Mi nombre es Carlos")],
    )

    analysis = _base_analysis()
    mock_client = _base_mock_client(analysis)

    pipeline_call_count = 0

    from app.analysis.universal.data_corrections import DataCorrectionsAxis

    async def _mock_pipeline(*args, **kwargs):
        nonlocal pipeline_call_count
        pipeline_call_count += 1
        return DataCorrectionsAxis(corrections=[])

    with (
        patch(
            "app.summarizer._get_openai_client",
            return_value=(mock_client, "gpt-4o-mini"),
        ),
        patch(
            "app.summarizer.run_data_corrections_pipeline", side_effect=_mock_pipeline
        ),
    ):
        assert corr_db.async_session_factory is not None
        async with corr_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    assert pipeline_call_count == 1, (
        f"run_data_corrections_pipeline must be called once per summarizer run, "
        f"got {pipeline_call_count}"
    )


async def test_pipeline_receives_current_lead_snapshot(corr_db):
    """Pipeline MUST receive current lead data (name, phone, email, age, etc.) as snapshot."""
    from app.summarizer import generate_summary_and_facts

    session_id = await _make_session(
        corr_db,
        turns=[("agent", "Hola"), ("user", "Soy Carlos")],
    )

    analysis = _base_analysis()
    mock_client = _base_mock_client(analysis)

    received_lead_data = {}

    from app.analysis.universal.data_corrections import DataCorrectionsAxis

    async def _capture_pipeline(*args, **kwargs):
        received_lead_data.update(kwargs.get("current_lead_data", {}))
        return DataCorrectionsAxis(corrections=[])

    with (
        patch(
            "app.summarizer._get_openai_client",
            return_value=(mock_client, "gpt-4o-mini"),
        ),
        patch(
            "app.summarizer.run_data_corrections_pipeline",
            side_effect=_capture_pipeline,
        ),
    ):
        assert corr_db.async_session_factory is not None
        async with corr_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    # Lead snapshot must include correctable fields
    assert "name" in received_lead_data, "Lead snapshot must include 'name'"
    assert "phone" in received_lead_data, "Lead snapshot must include 'phone'"
    assert (
        "email" in received_lead_data
    ), "Lead snapshot must include 'email' (may be None)"
    assert "age" in received_lead_data, "Lead snapshot must include 'age' (may be None)"
    assert received_lead_data["name"] == "Carlos Lopez"


# ---------------------------------------------------------------------------
# 4.3 — Corrections stored in facts["data_corrections"] for audit
# ---------------------------------------------------------------------------


async def test_applied_correction_updates_lead_and_stores_in_facts(corr_db):
    """Applied email correction MUST update Lead.email AND store in extracted_facts."""
    from app.summarizer import generate_summary_and_facts
    from app.leads.models import Lead
    from app.calls.models import CallSession
    from app.analysis.universal.data_corrections import (
        DataCorrectionsAxis,
        DataCorrection,
    )
    from sqlalchemy import select

    session_id = await _make_session(
        corr_db,
        turns=[("agent", "¿Su email?"), ("user", "Mi email es carlos@test.com")],
    )

    analysis = _base_analysis()
    mock_client = _base_mock_client(analysis)

    email_correction = DataCorrectionsAxis(
        corrections=[
            DataCorrection(
                field="email",
                current_value=None,
                corrected_value="carlos@test.com",
                confidence=0.95,
                evidence="Mi email es carlos@test.com",
                applied=True,
            )
        ]
    )

    async def _mock_pipeline(*args, **kwargs):
        return email_correction

    with (
        patch(
            "app.summarizer._get_openai_client",
            return_value=(mock_client, "gpt-4o-mini"),
        ),
        patch(
            "app.summarizer.run_data_corrections_pipeline", side_effect=_mock_pipeline
        ),
    ):
        assert corr_db.async_session_factory is not None
        async with corr_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with corr_db.async_session_factory() as db:
        # Lead.email must be updated
        lead_result = await db.execute(select(Lead).where(Lead.id == "corr-lead-001"))
        lead = lead_result.scalar_one()
        assert (
            lead.email == "carlos@test.com"
        ), f"Lead.email must be updated by correction, got {lead.email!r}"

        # extracted_facts must contain data_corrections audit
        cs_result = await db.execute(
            select(CallSession).where(CallSession.id == session_id)
        )
        cs = cs_result.scalar_one()
        assert cs.extracted_facts is not None
        assert "data_corrections" in cs.extracted_facts
        dc = cs.extracted_facts["data_corrections"]
        assert isinstance(dc, list), "data_corrections in facts must be a list"
        assert len(dc) >= 1, "At least one correction must be in the audit list"
        assert dc[0]["field"] == "email"
        assert dc[0]["corrected_value"] == "carlos@test.com"
        assert dc[0]["applied"] is True


async def test_applied_age_correction_updates_lead(corr_db):
    """Applied age correction MUST update Lead.age with integer value."""
    from app.summarizer import generate_summary_and_facts
    from app.leads.models import Lead
    from app.analysis.universal.data_corrections import (
        DataCorrectionsAxis,
        DataCorrection,
    )
    from sqlalchemy import select

    session_id = await _make_session(
        corr_db,
        turns=[("agent", "¿Qué edad tiene?"), ("user", "Tengo 42 años")],
    )

    analysis = _base_analysis()
    mock_client = _base_mock_client(analysis)

    age_correction = DataCorrectionsAxis(
        corrections=[
            DataCorrection(
                field="age",
                current_value=None,
                corrected_value="42",
                confidence=0.9,
                evidence="Tengo 42 años",
                applied=True,
            )
        ]
    )

    async def _mock_pipeline(*args, **kwargs):
        return age_correction

    with (
        patch(
            "app.summarizer._get_openai_client",
            return_value=(mock_client, "gpt-4o-mini"),
        ),
        patch(
            "app.summarizer.run_data_corrections_pipeline", side_effect=_mock_pipeline
        ),
    ):
        assert corr_db.async_session_factory is not None
        async with corr_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with corr_db.async_session_factory() as db:
        lead_result = await db.execute(select(Lead).where(Lead.id == "corr-lead-001"))
        lead = lead_result.scalar_one()
        assert lead.age == 42, f"Lead.age must be 42 (int), got {lead.age!r}"


async def test_no_corrections_leaves_lead_unchanged(corr_db):
    """Empty corrections axis MUST leave Lead fields unchanged."""
    from app.summarizer import generate_summary_and_facts
    from app.leads.models import Lead
    from app.analysis.universal.data_corrections import DataCorrectionsAxis
    from sqlalchemy import select

    session_id = await _make_session(
        corr_db,
        turns=[("agent", "Hola"), ("user", "Todo bien")],
    )

    analysis = _base_analysis()
    mock_client = _base_mock_client(analysis)

    async def _mock_pipeline(*args, **kwargs):
        return DataCorrectionsAxis(corrections=[])

    with (
        patch(
            "app.summarizer._get_openai_client",
            return_value=(mock_client, "gpt-4o-mini"),
        ),
        patch(
            "app.summarizer.run_data_corrections_pipeline", side_effect=_mock_pipeline
        ),
    ):
        assert corr_db.async_session_factory is not None
        async with corr_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with corr_db.async_session_factory() as db:
        lead_result = await db.execute(select(Lead).where(Lead.id == "corr-lead-001"))
        lead = lead_result.scalar_one()
        # Name and phone should be unchanged
        assert lead.name == "Carlos Lopez"
        assert lead.phone == "+5411000050"
        assert lead.email is None, "No correction → email stays None"
        assert lead.age is None, "No correction → age stays None"


async def test_invalid_correction_not_applied_but_in_audit(corr_db):
    """Invalid correction (age=200) MUST NOT update Lead but MUST appear in audit with applied=False."""
    from app.summarizer import generate_summary_and_facts
    from app.leads.models import Lead
    from app.calls.models import CallSession
    from app.analysis.universal.data_corrections import (
        DataCorrectionsAxis,
        DataCorrection,
    )
    from sqlalchemy import select

    session_id = await _make_session(
        corr_db,
        turns=[("agent", "¿Qué edad tiene?"), ("user", "Tengo 200 años")],
    )

    analysis = _base_analysis()
    mock_client = _base_mock_client(analysis)

    # GPT returns a correction with an invalid age (already processed by pipeline → applied=False)
    invalid_age_correction = DataCorrectionsAxis(
        corrections=[
            DataCorrection(
                field="age",
                current_value=None,
                corrected_value="200",
                confidence=0.9,
                evidence="Tengo 200 años",
                applied=False,
                rejection_reason="age 200 is greater than 120",
            )
        ]
    )

    async def _mock_pipeline(*args, **kwargs):
        return invalid_age_correction

    with (
        patch(
            "app.summarizer._get_openai_client",
            return_value=(mock_client, "gpt-4o-mini"),
        ),
        patch(
            "app.summarizer.run_data_corrections_pipeline", side_effect=_mock_pipeline
        ),
    ):
        assert corr_db.async_session_factory is not None
        async with corr_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with corr_db.async_session_factory() as db:
        # Lead.age must NOT be updated (still None)
        lead_result = await db.execute(select(Lead).where(Lead.id == "corr-lead-001"))
        lead = lead_result.scalar_one()
        assert (
            lead.age is None
        ), f"Invalid correction must NOT update Lead.age, got {lead.age!r}"

        # Audit list MUST contain the rejected correction with applied=False
        cs_result = await db.execute(
            select(CallSession).where(CallSession.id == session_id)
        )
        cs = cs_result.scalar_one()
        assert cs.extracted_facts is not None
        assert "data_corrections" in cs.extracted_facts

        dc = cs.extracted_facts["data_corrections"]
        assert isinstance(dc, list), "data_corrections must be a list"
        assert len(dc) == 1, f"Expected 1 correction in audit, got {len(dc)}"
        assert dc[0]["field"] == "age"
        assert (
            dc[0]["applied"] is False
        ), "Rejected correction must have applied=False in audit"
        assert (
            dc[0]["rejection_reason"] is not None
        ), "Rejected correction must have rejection_reason"


async def test_email_correction_updates_existing_nonnull_email(corr_db):
    """Correction MUST update Lead.email even when email was already set (non-null)."""
    from app.summarizer import generate_summary_and_facts
    from app.leads.models import Lead
    from app.analysis.universal.data_corrections import (
        DataCorrectionsAxis,
        DataCorrection,
    )
    from sqlalchemy import select

    # Pre-set email on the lead
    async with corr_db.async_session_factory() as sess:
        result = await sess.execute(select(Lead).where(Lead.id == "corr-lead-001"))
        lead = result.scalar_one()
        lead.email = "old-email@example.com"
        await sess.commit()

    session_id = await _make_session(
        corr_db,
        turns=[
            ("agent", "¿Cuál es su email?"),
            ("user", "Ahora es new-email@example.com"),
        ],
    )

    analysis = _base_analysis()
    mock_client = _base_mock_client(analysis)

    new_email_correction = DataCorrectionsAxis(
        corrections=[
            DataCorrection(
                field="email",
                current_value="old-email@example.com",
                corrected_value="new-email@example.com",
                confidence=0.95,
                evidence="Ahora es new-email@example.com",
                applied=True,
            )
        ]
    )

    async def _mock_pipeline(*args, **kwargs):
        return new_email_correction

    with (
        patch(
            "app.summarizer._get_openai_client",
            return_value=(mock_client, "gpt-4o-mini"),
        ),
        patch(
            "app.summarizer.run_data_corrections_pipeline", side_effect=_mock_pipeline
        ),
    ):
        assert corr_db.async_session_factory is not None
        async with corr_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with corr_db.async_session_factory() as db:
        lead_result = await db.execute(select(Lead).where(Lead.id == "corr-lead-001"))
        lead = lead_result.scalar_one()
        assert (
            lead.email == "new-email@example.com"
        ), f"Lead.email must be updated from old to new value, got {lead.email!r}"


async def test_pipeline_not_called_when_no_lead_id(corr_db):
    """run_data_corrections_pipeline MUST NOT be called when session has no lead_id."""
    from app.calls.service import create_session, add_transcript_turn
    from app.summarizer import generate_summary_and_facts

    # Create a session WITHOUT lead_id
    async with corr_db.async_session_factory() as sess:
        cs = await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id=None,  # No lead
        )
        cs.status = "completed"
        await add_transcript_turn(sess, cs.id, "user", "Hola")
        await sess.commit()
        session_id = cs.id

    analysis = _base_analysis()
    mock_client = _base_mock_client(analysis)

    pipeline_called = False

    from app.analysis.universal.data_corrections import DataCorrectionsAxis

    async def _mock_pipeline(*args, **kwargs):
        nonlocal pipeline_called
        pipeline_called = True
        return DataCorrectionsAxis(corrections=[])

    with (
        patch(
            "app.summarizer._get_openai_client",
            return_value=(mock_client, "gpt-4o-mini"),
        ),
        patch(
            "app.summarizer.run_data_corrections_pipeline", side_effect=_mock_pipeline
        ),
    ):
        assert corr_db.async_session_factory is not None
        async with corr_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    assert (
        pipeline_called is False
    ), "run_data_corrections_pipeline must NOT be called when session has no lead_id"
