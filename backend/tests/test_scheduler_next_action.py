"""Tests for scheduler integration with NextActionResult (qora-next-action, Issue #47).

Phase 4 — Summarizer + Scheduler Integration (Tasks 4.3-4.4).

Tests:
- auto_schedule reads NextActionResult action (not raw string)
- scheduled_at override from next_action_at when non-None
- no ScheduledCall for close_lead action
- no ScheduledCall for human_review action
- next_action_at=None falls back to calculate_scheduled_at()
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest_asyncio.fixture
async def sched_db_na(tmp_path: Path):
    """Isolated DB with quintana (scheduler_enabled=True) + test lead."""
    from app.core.config import Settings
    from app.core import database as db_module
    from pydantic import SecretStr

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/sched_na_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations
    await _init_db_with_migrations(db_module, settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead

        await seed_quintana(sess)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="NA Sched Lead",
            phone="+54110000888",
            lead_id="na-sched-lead-001",
        )
        await sess.commit()

    # Enable scheduler with new vocabulary defaults
    async with db_module.async_session_factory() as sess:
        from app.tenants.models import Client

        client = await sess.get(Client, "quintana-seguros")
        client.scheduler_enabled = True
        client.scheduler_cooldown_minutes = 60
        client.scheduler_allowed_hours_start = 9
        client.scheduler_allowed_hours_end = 20
        client.scheduler_retry_on_outcomes = (
            '["follow_up","retry_call","schedule_call"]'
        )
        await sess.commit()

    yield db_module
    await db_module.close_db()


# ===========================================================================
# Tests: auto_schedule with NextActionResult
# ===========================================================================


class TestAutoScheduleWithNextActionResult:
    """auto_schedule reads next_action_result.action and uses next_action_at override."""

    @pytest.mark.asyncio
    async def test_follow_up_action_creates_scheduled_call(self, sched_db_na):
        """auto_schedule creates ScheduledCall when next_action_suggested='follow_up'."""
        from app.scheduler.service import auto_schedule

        async with sched_db_na.async_session_factory() as sess:
            result = await auto_schedule(
                db=sess,
                session_id="sess-follow-001",
                lead_id="na-sched-lead-001",
                client_id="quintana-seguros",
                facts={"next_action_suggested": "follow_up"},
            )
            await sess.commit()

        assert result is not None
        assert result.trigger_reason == "auto_retry"
        assert result.status == "pending"

    @pytest.mark.asyncio
    async def test_retry_call_action_creates_scheduled_call(self, sched_db_na):
        """auto_schedule creates ScheduledCall when next_action_suggested='retry_call'."""
        from app.scheduler.service import auto_schedule

        async with sched_db_na.async_session_factory() as sess:
            result = await auto_schedule(
                db=sess,
                session_id="sess-retry-001",
                lead_id="na-sched-lead-001",
                client_id="quintana-seguros",
                facts={"next_action_suggested": "retry_call"},
            )
            await sess.commit()

        assert result is not None
        assert result.status == "pending"

    @pytest.mark.asyncio
    async def test_schedule_call_action_creates_scheduled_call(self, sched_db_na):
        """auto_schedule creates ScheduledCall when next_action_suggested='schedule_call'."""
        from app.scheduler.service import auto_schedule

        async with sched_db_na.async_session_factory() as sess:
            result = await auto_schedule(
                db=sess,
                session_id="sess-sched-001",
                lead_id="na-sched-lead-001",
                client_id="quintana-seguros",
                facts={"next_action_suggested": "schedule_call"},
            )
            await sess.commit()

        assert result is not None
        assert result.status == "pending"

    @pytest.mark.asyncio
    async def test_close_lead_does_not_create_scheduled_call(self, sched_db_na):
        """auto_schedule does NOT create ScheduledCall for close_lead action."""
        from app.scheduler.service import auto_schedule

        async with sched_db_na.async_session_factory() as sess:
            result = await auto_schedule(
                db=sess,
                session_id="sess-close-001",
                lead_id="na-sched-lead-001",
                client_id="quintana-seguros",
                facts={"next_action_suggested": "close_lead"},
            )
            await sess.commit()

        assert result is None

    @pytest.mark.asyncio
    async def test_human_review_does_not_create_scheduled_call(self, sched_db_na):
        """auto_schedule does NOT create ScheduledCall for human_review action."""
        from app.scheduler.service import auto_schedule

        async with sched_db_na.async_session_factory() as sess:
            result = await auto_schedule(
                db=sess,
                session_id="sess-review-001",
                lead_id="na-sched-lead-001",
                client_id="quintana-seguros",
                facts={"next_action_suggested": "human_review"},
            )
            await sess.commit()

        assert result is None

    @pytest.mark.asyncio
    async def test_next_action_at_override_used_as_scheduled_at(self, sched_db_na):
        """When next_action_result.next_action_at is non-None, it overrides calculate_scheduled_at.

        Phase 4: auto_schedule reads facts["next_action_result"]["next_action_at"]
        and uses it as scheduled_at directly.
        """
        from app.scheduler.service import auto_schedule

        # Specific future datetime as override
        override_time = datetime(2026, 5, 8, 14, 0, 0, tzinfo=timezone.utc)

        async with sched_db_na.async_session_factory() as sess:
            result = await auto_schedule(
                db=sess,
                session_id="sess-override-001",
                lead_id="na-sched-lead-001",
                client_id="quintana-seguros",
                facts={
                    "next_action_suggested": "schedule_call",
                    "next_action_result": {
                        "action": "schedule_call",
                        "reason": "callback commitment tomorrow",
                        "confidence": "high",
                        "decided_by": "rules",
                        "next_action_at": override_time.isoformat(),
                        "priority": "normal",
                    },
                },
            )
            await sess.commit()

        assert result is not None
        # scheduled_at should equal the override time
        assert result.scheduled_at == override_time

    @pytest.mark.asyncio
    async def test_none_next_action_at_falls_back_to_calculate(self, sched_db_na):
        """When next_action_result.next_action_at is None, calculate_scheduled_at is used."""
        from app.scheduler.service import auto_schedule

        async with sched_db_na.async_session_factory() as sess:
            result = await auto_schedule(
                db=sess,
                session_id="sess-fallback-001",
                lead_id="na-sched-lead-001",
                client_id="quintana-seguros",
                facts={
                    "next_action_suggested": "retry_call",
                    "next_action_result": {
                        "action": "retry_call",
                        "reason": "no answer",
                        "confidence": "high",
                        "decided_by": "rules",
                        "next_action_at": None,
                        "priority": "normal",
                    },
                },
            )
            await sess.commit()

        assert result is not None
        # scheduled_at should be in the future (calculated by calculate_scheduled_at)
        assert result.scheduled_at > datetime.now(timezone.utc)


# ===========================================================================
# Tests: Summarizer post-analysis wiring
# ===========================================================================


class TestSummarizerNextActionWiring:
    """Summarizer builds NextActionContext and calls run_next_action_pipeline."""

    @pytest_asyncio.fixture
    async def seeded_db_phase4(self, tmp_path: Path):
        """Isolated DB with quintana-seguros + one test lead."""
        from app.core.config import Settings
        from app.core import database as db_module
        from pydantic import SecretStr

        settings = Settings(
            openai_api_key=SecretStr("sk-test"),
            elevenlabs_api_key=SecretStr("el-test"),
            database_url=f"sqlite+aiosqlite:///{tmp_path}/phase4_test.db",
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
                name="Phase4 Lead",
                phone="+54110000777",
                lead_id="phase4-lead-001",
            )
            await sess.commit()

        yield db_module
        await db_module.close_db()

    def _make_summarizer_mock(self, next_action_result_dict: dict):
        """Build a mock that patches _call_gpt_summarize to return controlled facts."""
        from app.analysis.schema import PostCallAnalysis
        from app.analysis.universal.outcome import CallOutcome
        from app.analysis.universal.commitments import CommitmentsAxis
        from app.analysis.universal.objections import ObjectionsAxis
        from app.analysis.universal.interest.interests import InterestsAxis

        analysis = PostCallAnalysis(
            summary="Test summary for phase 4.",
            call_outcome=CallOutcome(
                classification="completed_positive",
                reason="Good call",
                confidence="high",
            ),
            interest_level=70,
            commitments=CommitmentsAxis(),
            objections=ObjectionsAxis(),
            detected_interests=InterestsAxis(),
        )

        facts = analysis.model_dump()
        facts["next_action_suggested"] = next_action_result_dict["action"]
        facts["next_action_result"] = next_action_result_dict

        return facts

    @pytest.mark.asyncio
    async def test_summarizer_sets_next_action_suggested_from_pipeline(
        self, seeded_db_phase4
    ):
        """Summarizer sets next_action_suggested from run_next_action_pipeline result."""
        from app.summarizer import generate_summary_and_facts
        from app.leads.models import Lead
        from sqlalchemy import select

        session_id = await self._create_session(seeded_db_phase4)

        next_action_result = {
            "action": "follow_up",
            "reason": "High interest",
            "confidence": "high",
            "decided_by": "rules",
            "next_action_at": None,
            "priority": "normal",
        }

        facts = self._make_summarizer_mock(next_action_result)

        with patch(
            "app.summarizer._call_gpt_summarize",
            return_value=("Test summary for phase 4.", facts),
        ):
            async with seeded_db_phase4.async_session_factory() as db:
                await generate_summary_and_facts(session_id, db)
                await db.commit()

        async with seeded_db_phase4.async_session_factory() as db:
            result = await db.execute(select(Lead).where(Lead.id == "phase4-lead-001"))
            lead = result.scalar_one()
            assert lead.next_action == "follow_up"

    @pytest.mark.asyncio
    async def test_summarizer_sets_lead_next_action_at_from_pipeline(
        self, seeded_db_phase4
    ):
        """Summarizer sets Lead.next_action_at from NextActionResult.next_action_at."""
        from app.summarizer import generate_summary_and_facts
        from app.leads.models import Lead
        from sqlalchemy import select

        session_id = await self._create_session(seeded_db_phase4)

        scheduled_at = datetime(2026, 5, 8, 14, 0, 0, tzinfo=timezone.utc)
        next_action_result = {
            "action": "schedule_call",
            "reason": "Callback commitment",
            "confidence": "high",
            "decided_by": "rules",
            "next_action_at": scheduled_at.isoformat(),
            "priority": "normal",
        }

        facts = self._make_summarizer_mock(next_action_result)

        with patch(
            "app.summarizer._call_gpt_summarize",
            return_value=("Test summary for phase 4.", facts),
        ):
            async with seeded_db_phase4.async_session_factory() as db:
                await generate_summary_and_facts(session_id, db)
                await db.commit()

        async with seeded_db_phase4.async_session_factory() as db:
            result = await db.execute(select(Lead).where(Lead.id == "phase4-lead-001"))
            lead = result.scalar_one()
            assert lead.next_action_at is not None
            # The stored datetime should match scheduled_at
            stored_dt = lead.next_action_at
            if stored_dt.tzinfo is None:
                stored_dt = stored_dt.replace(tzinfo=timezone.utc)
            assert abs((stored_dt - scheduled_at).total_seconds()) < 2

    @pytest.mark.asyncio
    async def test_summarizer_close_lead_sets_do_not_call(self, seeded_db_phase4):
        """close_lead action from pipeline sets Lead.do_not_call = True."""
        from app.summarizer import generate_summary_and_facts
        from app.leads.models import Lead
        from sqlalchemy import select

        session_id = await self._create_session(seeded_db_phase4)

        next_action_result = {
            "action": "close_lead",
            "reason": "Hostile outcome",
            "confidence": "high",
            "decided_by": "rules",
            "next_action_at": None,
            "priority": "normal",
        }

        facts = self._make_summarizer_mock(next_action_result)
        facts["next_action_suggested"] = "close_lead"

        with patch(
            "app.summarizer._call_gpt_summarize",
            return_value=("Test summary for phase 4.", facts),
        ):
            async with seeded_db_phase4.async_session_factory() as db:
                await generate_summary_and_facts(session_id, db)
                await db.commit()

        async with seeded_db_phase4.async_session_factory() as db:
            result = await db.execute(select(Lead).where(Lead.id == "phase4-lead-001"))
            lead = result.scalar_one()
            assert lead.do_not_call is True

    @pytest.mark.asyncio
    async def test_summarizer_stores_next_action_result_in_facts(
        self, seeded_db_phase4
    ):
        """Summarizer stores full next_action_result dict in extracted_facts."""
        from app.summarizer import generate_summary_and_facts
        from app.calls.models import CallSession
        from sqlalchemy import select
        import json

        session_id = await self._create_session(seeded_db_phase4)

        next_action_result = {
            "action": "follow_up",
            "reason": "High interest",
            "confidence": "high",
            "decided_by": "rules",
            "next_action_at": None,
            "priority": "normal",
        }

        facts = self._make_summarizer_mock(next_action_result)

        with patch(
            "app.summarizer._call_gpt_summarize",
            return_value=("Test summary for phase 4.", facts),
        ):
            async with seeded_db_phase4.async_session_factory() as db:
                await generate_summary_and_facts(session_id, db)
                await db.commit()

        async with seeded_db_phase4.async_session_factory() as db:
            result = await db.execute(
                select(CallSession).where(CallSession.id == session_id)
            )
            cs = result.scalar_one()
            stored_facts = cs.extracted_facts
            if isinstance(stored_facts, str):
                stored_facts = json.loads(stored_facts)

            assert "next_action_result" in stored_facts
            assert stored_facts["next_action_result"]["action"] == "follow_up"
            assert stored_facts["next_action_result"]["decided_by"] == "rules"

    async def _create_session(self, db_module) -> str:
        """Helper: create completed CallSession with 2 turns for phase4-lead-001."""
        from app.calls.service import create_session, add_transcript_turn

        async with db_module.async_session_factory() as sess:
            cs = await create_session(
                sess,
                client_id="quintana-seguros",
                lead_id="phase4-lead-001",
            )
            cs.status = "completed"
            await add_transcript_turn(sess, cs.id, "agent", "Hola, le llamo")
            await add_transcript_turn(sess, cs.id, "user", "Sí me interesa")
            await sess.commit()
            return cs.id


# ===========================================================================
# Tests: next_action_result.action as PRIMARY source (spec requirement)
# RED phase — these prove the scheduler reads the rich result dict first
# ===========================================================================


class TestAutoScheduleReadsNextActionResultAction:
    """Spec: auto_schedule MUST read next_action_result.action as primary gate.

    Three scenarios required by the spec:
    1. Only next_action_result.action present (no next_action_suggested) → schedules
    2. next_action_result.action = close_lead (no next_action_suggested) → blocks
    3. Both present, next_action_result.action wins (even when next_action_suggested disagrees)
    """

    @pytest.mark.asyncio
    async def test_next_action_result_action_schedules_without_legacy_field(
        self, sched_db_na
    ):
        """auto_schedule creates ScheduledCall from next_action_result.action alone.

        facts has next_action_result.action='schedule_call' but NO next_action_suggested.
        The scheduler must still create the call — proving it reads next_action_result.action.
        """
        from app.scheduler.service import auto_schedule

        async with sched_db_na.async_session_factory() as sess:
            result = await auto_schedule(
                db=sess,
                session_id="sess-rich-only-001",
                lead_id="na-sched-lead-001",
                client_id="quintana-seguros",
                facts={
                    # No next_action_suggested — rich result is the only source
                    "next_action_result": {
                        "action": "schedule_call",
                        "reason": "Commitment to call back tomorrow",
                        "confidence": "high",
                        "decided_by": "rules",
                        "next_action_at": None,
                        "priority": "normal",
                    },
                },
            )
            await sess.commit()

        # Must schedule because next_action_result.action='schedule_call' is in retry_outcomes
        assert result is not None
        assert result.trigger_reason == "auto_retry"
        assert result.status == "pending"

    @pytest.mark.asyncio
    async def test_next_action_result_action_blocks_when_close_lead(self, sched_db_na):
        """auto_schedule blocks when next_action_result.action='close_lead' (no legacy field).

        facts has next_action_result.action='close_lead' but NO next_action_suggested.
        close_lead is not in retry_outcomes → must return None.
        """
        from app.scheduler.service import auto_schedule

        async with sched_db_na.async_session_factory() as sess:
            result = await auto_schedule(
                db=sess,
                session_id="sess-rich-close-001",
                lead_id="na-sched-lead-001",
                client_id="quintana-seguros",
                facts={
                    # No next_action_suggested — close_lead should block
                    "next_action_result": {
                        "action": "close_lead",
                        "reason": "Hostile / irreversible rejection",
                        "confidence": "high",
                        "decided_by": "rules",
                        "next_action_at": None,
                        "priority": "high",
                    },
                },
            )
            await sess.commit()

        assert result is None

    @pytest.mark.asyncio
    async def test_next_action_result_action_wins_over_legacy_when_both_present(
        self, sched_db_na
    ):
        """next_action_result.action takes priority when both fields are present.

        next_action_suggested says 'close_lead' (would block),
        but next_action_result.action says 'follow_up' (should schedule).
        The rich result must win → call is created.
        """
        from app.scheduler.service import auto_schedule

        async with sched_db_na.async_session_factory() as sess:
            result = await auto_schedule(
                db=sess,
                session_id="sess-priority-001",
                lead_id="na-sched-lead-001",
                client_id="quintana-seguros",
                facts={
                    # Legacy says block — rich result says schedule
                    "next_action_suggested": "close_lead",
                    "next_action_result": {
                        "action": "follow_up",
                        "reason": "Engine override: high interest detected",
                        "confidence": "high",
                        "decided_by": "rules",
                        "next_action_at": None,
                        "priority": "normal",
                    },
                },
            )
            await sess.commit()

        # next_action_result.action='follow_up' wins → ScheduledCall created
        assert result is not None
        assert result.trigger_reason == "auto_retry"
