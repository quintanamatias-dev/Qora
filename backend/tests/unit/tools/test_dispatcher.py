"""Unit tests for tools dispatcher.

RED: References app.tools.dispatcher which is not yet implemented.
Covers: tool routing, error handling for unknown tools.
"""

from __future__ import annotations

from pathlib import Path

import pytest_asyncio
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db(tmp_path: Path):
    """DB module with seeded Quintana + test leads."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/dispatcher_test.db",
    )
    await db_module.init_db(settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import seed_leads

        await seed_quintana(sess)
        await seed_leads(sess)
        await sess.commit()

    yield db_module
    await db_module.close_db()


# ---------------------------------------------------------------------------
# T5.1: Dispatcher tests
# ---------------------------------------------------------------------------


async def test_dispatcher_routes_get_lead_details(db):
    """dispatch_tool routes 'get_lead_details' to the correct handler."""
    from app.tools.dispatcher import dispatch_tool

    async with db.async_session_factory() as sess:
        result = await dispatch_tool(
            tool_name="get_lead_details",
            tool_args={"lead_id": "lead-quintana-001"},
            client_id="quintana-seguros",
            lead_id="lead-quintana-001",
            session=sess,
        )

    assert "error" not in result
    assert result["id"] == "lead-quintana-001"


async def test_dispatcher_routes_mark_not_interested(db):
    """dispatch_tool routes 'mark_not_interested' to the correct handler."""
    from app.tools.dispatcher import dispatch_tool

    async with db.async_session_factory() as sess:
        result = await dispatch_tool(
            tool_name="mark_not_interested",
            tool_args={
                "lead_id": "lead-quintana-003",
                "reason": "Ya tiene seguro",
            },
            client_id="quintana-seguros",
            lead_id="lead-quintana-003",
            session=sess,
        )

    assert "error" not in result
    assert result["status"] == "not_interested"


async def test_dispatcher_returns_error_for_unknown_tool(db):
    """dispatch_tool returns error dict for unknown tool name."""
    from app.tools.dispatcher import dispatch_tool

    async with db.async_session_factory() as sess:
        result = await dispatch_tool(
            tool_name="unknown_tool",
            tool_args={},
            client_id="quintana-seguros",
            lead_id=None,
            session=sess,
        )

    assert "error" in result
    assert "unknown_tool" in result["error"]


# ---------------------------------------------------------------------------
# Round 2 fix: dispatcher must pass client_id to schedule_followup
# Issue 1 — TZ fix incomplete in dispatcher path
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_with_scheduler(tmp_path: Path):
    """DB with quintana (scheduler_enabled=True, America/New_York tz) + test leads."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/dispatcher_sched_test.db",
    )
    await db_module.init_db(settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import seed_leads

        await seed_quintana(sess)
        await seed_leads(sess)
        await sess.commit()

    # Enable scheduler and set timezone to New York (UTC-5 in winter)
    async with db_module.async_session_factory() as sess:
        from app.tenants.models import Client

        client = await sess.get(Client, "quintana-seguros")
        client.scheduler_enabled = True
        client.scheduler_timezone = "America/New_York"
        await sess.commit()

    yield db_module
    await db_module.close_db()


async def test_dispatcher_passes_client_id_to_schedule_followup(db_with_scheduler):
    """dispatch_tool must pass client_id to schedule_followup so TZ is resolved.

    Without client_id, naive datetimes fall back to UTC instead of client TZ.
    This verifies the dispatcher actually passes client_id so the TZ is loaded
    before date parsing — the ScheduledCall's scheduled_at must use client TZ,
    not UTC fallback.
    """
    from app.tools.dispatcher import dispatch_tool
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select

    # Naive datetime "2026-06-01T11:00" — the two TZ interpretations diverge:
    # - UTC fallback:      11:00 UTC → 7:00 AM NY (before 9AM window) → clamp to 9AM NY = 13:00 UTC
    # - America/New_York: 11:00 AM NY → 15:00 UTC (within [9,20) window) → no clamp = 15:00 UTC
    # If client_id is passed correctly, result must be 15:00 UTC (New York interpretation).
    # If client_id is NOT passed, result would be 13:00 UTC (UTC fallback + clamp).
    async with db_with_scheduler.async_session_factory() as sess:
        result = await dispatch_tool(
            tool_name="schedule_followup",
            tool_args={
                "lead_id": "lead-quintana-003",
                "followup_date": "2026-06-01T11:00",
            },
            client_id="quintana-seguros",
            lead_id="lead-quintana-003",
            session=sess,
        )
        await sess.commit()

    assert "error" not in result, f"Expected success, got: {result}"

    # Verify a ScheduledCall was created (scheduler_enabled=True)
    async with db_with_scheduler.async_session_factory() as sess:
        rows = await sess.execute(
            select(ScheduledCall).where(ScheduledCall.lead_id == "lead-quintana-003")
        )
        sc = rows.scalar_one_or_none()
        assert sc is not None, "ScheduledCall should have been created"
        assert sc.scheduled_at is not None
        # With client_id correctly passed → New York TZ used:
        # 11:00 AM NY (EDT, UTC-4) = 15:00 UTC → within [9,20) → no clamp → 15:00 UTC
        assert sc.scheduled_at.hour == 15, (
            f"Expected scheduled_at 15:00 UTC (11AM New_York → 15 UTC), "
            f"got {sc.scheduled_at}. "
            f"If 13:00, client_id was not passed (UTC fallback + clamp)."
        )
