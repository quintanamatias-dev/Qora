"""Tests for auto-schedule hook in summarizer — Phase 6 (Task 3.1 RED).

Covers:
- Auto-schedule fires after eligible call (scheduler_enabled=True, valid outcome)
- Summarizer failure in auto_schedule does NOT block lead merge
- Auto-schedule skips do_not_call lead
- Auto-schedule skips ineligible outcome
- Graceful failure in auto_schedule
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
    """DB with quintana (scheduler_enabled=True) + test lead."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/sched_hook_test.db",
    )
    await db_module.init_db(settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead

        await seed_quintana(sess)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Hook Test Lead",
            phone="+5411000088",
            lead_id="hook-lead-001",
        )
        await sess.commit()

    # Enable scheduler on quintana
    async with db_module.async_session_factory() as sess:
        from app.tenants.models import Client

        client = await sess.get(Client, "quintana-seguros")
        client.scheduler_enabled = True
        client.scheduler_retry_on_outcomes = '["busy","no_answer","follow_up","call_again"]'
        await sess.commit()

    yield db_module
    await db_module.close_db()


def _make_parse_response_with_action(next_action: str) -> MagicMock:
    """Build mock parse response with a specific next_action_suggested."""
    from app.analysis_schema import (
        PostCallAnalysis,
        CallOutcome,
        DetectedInterests,
        IdentifiedProblem,
    )

    analysis = PostCallAnalysis(
        summary="Test summary.",
        objections=[],
        interest_level=60,
        current_insurance=None,
        next_action_suggested=next_action,
        misc_notes="",
        call_outcome=CallOutcome(
            classification="follow_up",
            reason="Lead asked to be called again.",
            engagement_quality="medium",
        ),
        detected_interests=DetectedInterests(),
        identified_problem=IdentifiedProblem(
            primary_need="Needs coverage.",
            urgency="medium",
        ),
    )

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.parsed = analysis
    mock_response.choices[0].message.refusal = None
    return mock_response


async def _create_session_with_turns(db_module, lead_id: str) -> str:
    """Create a completed CallSession with 2 turns."""
    from app.calls.service import create_session, add_transcript_turn

    async with db_module.async_session_factory() as sess:
        cs = await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id=lead_id,
        )
        cs.status = "completed"
        await add_transcript_turn(sess, cs.id, "agent", "Hola")
        await add_transcript_turn(sess, cs.id, "user", "Sí me interesa")
        await sess.commit()
        return cs.id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_auto_schedule_fires_after_eligible_call(seeded_db):
    """Summarizer calls auto_schedule after merge when client is enabled and outcome eligible."""
    from app.summarizer import generate_summary_and_facts
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select

    session_id = await _create_session_with_turns(seeded_db, "hook-lead-001")

    mock_client = AsyncMock()
    mock_client.chat.completions.parse.return_value = _make_parse_response_with_action(
        "call_again"
    )

    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    # A ScheduledCall should have been created
    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(ScheduledCall).where(ScheduledCall.lead_id == "hook-lead-001")
        )
        sc = result.scalar_one_or_none()
        assert sc is not None
        assert sc.trigger_reason == "auto_retry"
        assert sc.status == "pending"


async def test_auto_schedule_skips_ineligible_outcome_in_summarizer(seeded_db):
    """When next_action='send_quote', auto_schedule does NOT create ScheduledCall."""
    from app.summarizer import generate_summary_and_facts
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select

    session_id = await _create_session_with_turns(seeded_db, "hook-lead-001")

    mock_client = AsyncMock()
    mock_client.chat.completions.parse.return_value = _make_parse_response_with_action(
        "send_quote"
    )

    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(ScheduledCall).where(ScheduledCall.lead_id == "hook-lead-001")
        )
        sc = result.scalar_one_or_none()
        assert sc is None


async def test_summarizer_auto_schedule_failure_does_not_block_lead_merge(seeded_db):
    """If auto_schedule raises, summarizer catches it and lead facts are still persisted."""
    from app.summarizer import generate_summary_and_facts
    from app.leads.models import Lead
    from sqlalchemy import select

    session_id = await _create_session_with_turns(seeded_db, "hook-lead-001")

    mock_client = AsyncMock()
    mock_client.chat.completions.parse.return_value = _make_parse_response_with_action(
        "call_again"
    )

    # Patch auto_schedule to raise
    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ), patch(
        "app.scheduler.service.auto_schedule",
        side_effect=Exception("Scheduler exploded"),
    ):
        async with seeded_db.async_session_factory() as db:
            # Must NOT raise
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    # Lead facts should still be persisted (lead merge happened BEFORE auto_schedule)
    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(Lead).where(Lead.id == "hook-lead-001")
        )
        lead = result.scalar_one()
        assert lead.summary_last_call is not None
        assert lead.summary_last_call == "Test summary."


async def test_auto_schedule_skips_do_not_call_lead_in_summarizer(seeded_db):
    """When lead.do_not_call=True, auto_schedule does NOT create ScheduledCall."""
    from app.summarizer import generate_summary_and_facts
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select

    # Mark lead as DNC first
    async with seeded_db.async_session_factory() as sess:
        from app.leads.models import Lead

        lead = await sess.get(Lead, "hook-lead-001")
        lead.do_not_call = True
        await sess.commit()

    session_id = await _create_session_with_turns(seeded_db, "hook-lead-001")

    mock_client = AsyncMock()
    mock_client.chat.completions.parse.return_value = _make_parse_response_with_action(
        "call_again"
    )

    with patch(
        "app.summarizer._get_openai_client", return_value=(mock_client, "gpt-4o-mini")
    ):
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(ScheduledCall).where(ScheduledCall.lead_id == "hook-lead-001")
        )
        sc = result.scalar_one_or_none()
        assert sc is None
