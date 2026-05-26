"""RED tests for confirmed security/correctness fixes (Issues 1–7).

Issues covered:
1. Multi-tenant isolation breach — cross-tenant lead scheduling
2. Manual create bypasses allowed hours
3. Scheduler config unvalidated (invalid TZ, hour range, negative values, bad outcomes)
4. Date filter 500 (invalid scheduled_from/scheduled_to)
5. Naive datetime treated as UTC in schedule_followup
6. Naive datetimes in schema (offset-aware required)
7. Missing tests for negative paths (this file IS those tests)
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def two_tenant_app(tmp_path: Path):
    """Two isolated clients: alpha-client and beta-client, each with one lead."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/security_test.db",
    )
    await db_module.init_db(settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.models import Client
        from app.leads.service import create_lead

        alpha = Client(
            id="alpha-client",
            name="Alpha Broker",
            agent_name="AgentAlpha",
            voice_id="v-alpha",
            is_active=True,
            scheduler_enabled=True,
        )
        beta = Client(
            id="beta-client",
            name="Beta Broker",
            agent_name="AgentBeta",
            voice_id="v-beta",
            is_active=True,
            scheduler_enabled=True,
        )
        sess.add(alpha)
        sess.add(beta)
        await sess.flush()

        await create_lead(
            sess,
            client_id="alpha-client",
            name="Alpha Lead",
            phone="+5411000001",
            lead_id="alpha-lead-001",
        )
        await create_lead(
            sess,
            client_id="beta-client",
            name="Beta Lead",
            phone="+5411000002",
            lead_id="beta-lead-001",
        )
        await sess.commit()

    from app.scheduler.router import router as scheduler_router
    from app.clients.router import router as clients_router
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.include_router(scheduler_router, prefix="/api/v1")
    test_app.include_router(clients_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        yield client

    await db_module.close_db()


@pytest_asyncio.fixture
async def hours_app(tmp_path: Path):
    """Client with scheduler_enabled, narrow allowed hours: 9–20 Buenos Aires."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/hours_test.db",
    )
    await db_module.init_db(settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.models import Client
        from app.leads.service import create_lead

        c = Client(
            id="hours-client",
            name="Hours Broker",
            agent_name="AgentH",
            voice_id="v-h",
            is_active=True,
            scheduler_enabled=True,
            scheduler_allowed_hours_start=9,
            scheduler_allowed_hours_end=20,
            scheduler_timezone="America/Argentina/Buenos_Aires",
        )
        sess.add(c)
        await sess.flush()
        await create_lead(
            sess,
            client_id="hours-client",
            name="Hours Lead",
            phone="+5411000099",
            lead_id="hours-lead-001",
        )
        await sess.commit()

    from app.scheduler.router import router as scheduler_router
    from app.clients.router import router as clients_router
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.include_router(scheduler_router, prefix="/api/v1")
    test_app.include_router(clients_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        yield client

    await db_module.close_db()


@pytest_asyncio.fixture
async def followup_app(tmp_path: Path):
    """Minimal app for schedule_followup timezone tests."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/followup_test.db",
    )
    await db_module.init_db(settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.models import Client
        from app.leads.service import create_lead
        from app.leads.models import Lead

        c = Client(
            id="fu-client",
            name="Followup Broker",
            agent_name="AgentFU",
            voice_id="v-fu",
            is_active=True,
            scheduler_enabled=True,
            scheduler_allowed_hours_start=9,
            scheduler_allowed_hours_end=20,
            scheduler_timezone="America/Argentina/Buenos_Aires",
        )
        sess.add(c)
        await sess.flush()
        await create_lead(
            sess,
            client_id="fu-client",
            name="FU Lead",
            phone="+5411000055",
            lead_id="fu-lead-001",
        )
        await sess.flush()
        # Advance lead to "called" so follow_up transition is valid
        lead = await sess.get(Lead, "fu-lead-001")
        lead.status = "called"
        await sess.commit()

    yield db_module
    await db_module.close_db()


# ---------------------------------------------------------------------------
# Issue 1: Multi-tenant isolation breach — cross-tenant lead scheduling
# ---------------------------------------------------------------------------


async def test_create_scheduled_call_with_orphan_lead_returns_404(
    two_tenant_app: AsyncClient,
):
    """POST with a nonexistent lead_id must return 404, not 201."""
    future_dt = datetime(2026, 6, 1, 15, 0, 0, tzinfo=timezone.utc).isoformat()
    response = await two_tenant_app.post(
        "/api/v1/scheduler/alpha-client/queue",
        json={"lead_id": "nonexistent-lead-999", "scheduled_at": future_dt},
    )
    assert response.status_code == 404
    assert "lead" in response.json()["detail"]["error"]


async def test_create_scheduled_call_with_cross_tenant_lead_returns_403(
    two_tenant_app: AsyncClient,
):
    """POST with beta's lead_id against alpha's queue must return 403."""
    future_dt = datetime(2026, 6, 1, 15, 0, 0, tzinfo=timezone.utc).isoformat()
    response = await two_tenant_app.post(
        "/api/v1/scheduler/alpha-client/queue",
        json={"lead_id": "beta-lead-001", "scheduled_at": future_dt},
    )
    assert response.status_code == 403
    assert "lead" in response.json()["detail"]["error"]


async def test_create_scheduled_call_own_lead_succeeds(two_tenant_app: AsyncClient):
    """POST with alpha's own lead_id against alpha's queue returns 201."""
    future_dt = datetime(2026, 6, 1, 15, 0, 0, tzinfo=timezone.utc).isoformat()
    response = await two_tenant_app.post(
        "/api/v1/scheduler/alpha-client/queue",
        json={"lead_id": "alpha-lead-001", "scheduled_at": future_dt},
    )
    assert response.status_code == 201
    assert response.json()["lead_id"] == "alpha-lead-001"


# ---------------------------------------------------------------------------
# Issue 2: Manual create bypasses allowed hours
# ---------------------------------------------------------------------------


async def test_manual_create_outside_allowed_hours_returns_422(
    hours_app: AsyncClient,
):
    """POST with a datetime outside allowed hours (03:00 Buenos Aires) → 422."""
    # 03:00 Buenos Aires = 06:00 UTC (UTC-3)
    outside_hours_dt = datetime(2026, 6, 1, 6, 0, 0, tzinfo=timezone.utc).isoformat()
    response = await hours_app.post(
        "/api/v1/scheduler/hours-client/queue",
        json={"lead_id": "hours-lead-001", "scheduled_at": outside_hours_dt},
    )
    assert response.status_code == 422
    assert "allowed hours" in response.json()["detail"]["error"]


async def test_manual_create_inside_allowed_hours_succeeds(hours_app: AsyncClient):
    """POST with a datetime inside allowed hours (15:00 Buenos Aires) → 201."""
    # 15:00 Buenos Aires = 18:00 UTC (UTC-3)
    inside_hours_dt = datetime(2026, 6, 1, 18, 0, 0, tzinfo=timezone.utc).isoformat()
    response = await hours_app.post(
        "/api/v1/scheduler/hours-client/queue",
        json={"lead_id": "hours-lead-001", "scheduled_at": inside_hours_dt},
    )
    assert response.status_code == 201


# ---------------------------------------------------------------------------
# Issue 3: Scheduler config unvalidated
# ---------------------------------------------------------------------------


async def test_patch_client_invalid_timezone_returns_422(hours_app: AsyncClient):
    """PATCH with invalid timezone string returns 422."""
    response = await hours_app.patch(
        "/api/v1/clients/hours-client",
        json={"scheduler_timezone": "Not/A/Real/TZ"},
    )
    assert response.status_code == 422


async def test_patch_client_valid_timezone_succeeds(hours_app: AsyncClient):
    """PATCH with valid timezone string returns 200."""
    response = await hours_app.patch(
        "/api/v1/clients/hours-client",
        json={"scheduler_timezone": "America/New_York"},
    )
    assert response.status_code == 200
    assert response.json()["scheduler_timezone"] == "America/New_York"


async def test_patch_client_invalid_hour_range_start_negative_returns_422(
    hours_app: AsyncClient,
):
    """PATCH with scheduler_allowed_hours_start < 0 returns 422."""
    response = await hours_app.patch(
        "/api/v1/clients/hours-client",
        json={"scheduler_allowed_hours_start": -1},
    )
    assert response.status_code == 422


async def test_patch_client_invalid_hour_range_end_over_23_returns_422(
    hours_app: AsyncClient,
):
    """PATCH with scheduler_allowed_hours_end > 23 returns 422."""
    response = await hours_app.patch(
        "/api/v1/clients/hours-client",
        json={"scheduler_allowed_hours_end": 25},
    )
    assert response.status_code == 422


async def test_patch_client_invalid_hour_range_start_gte_end_returns_422(
    hours_app: AsyncClient,
):
    """PATCH where start_hour >= end_hour returns 422."""
    response = await hours_app.patch(
        "/api/v1/clients/hours-client",
        json={"scheduler_allowed_hours_start": 20, "scheduler_allowed_hours_end": 9},
    )
    assert response.status_code == 422


async def test_patch_client_negative_max_attempts_returns_422(hours_app: AsyncClient):
    """PATCH with scheduler_max_attempts < 1 returns 422."""
    response = await hours_app.patch(
        "/api/v1/clients/hours-client",
        json={"scheduler_max_attempts": 0},
    )
    assert response.status_code == 422


async def test_patch_client_negative_cooldown_returns_422(hours_app: AsyncClient):
    """PATCH with scheduler_cooldown_minutes < 0 returns 422."""
    response = await hours_app.patch(
        "/api/v1/clients/hours-client",
        json={"scheduler_cooldown_minutes": -5},
    )
    assert response.status_code == 422


async def test_patch_client_invalid_retry_outcomes_returns_422(hours_app: AsyncClient):
    """PATCH with non-JSON scheduler_retry_on_outcomes returns 422."""
    response = await hours_app.patch(
        "/api/v1/clients/hours-client",
        json={"scheduler_retry_on_outcomes": "not-valid-json"},
    )
    assert response.status_code == 422


async def test_patch_client_non_list_retry_outcomes_returns_422(
    hours_app: AsyncClient,
):
    """PATCH with non-list JSON scheduler_retry_on_outcomes returns 422."""
    response = await hours_app.patch(
        "/api/v1/clients/hours-client",
        json={"scheduler_retry_on_outcomes": '{"key": "value"}'},
    )
    assert response.status_code == 422


async def test_patch_client_valid_retry_outcomes_succeeds(hours_app: AsyncClient):
    """PATCH with valid JSON list retry_outcomes returns 200."""
    response = await hours_app.patch(
        "/api/v1/clients/hours-client",
        json={"scheduler_retry_on_outcomes": '["busy","no_answer"]'},
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Issue 4: Date filter 500 — invalid scheduled_from/scheduled_to
# ---------------------------------------------------------------------------


async def test_list_queue_invalid_scheduled_from_returns_422(hours_app: AsyncClient):
    """GET queue with invalid scheduled_from returns 422, not 500."""
    response = await hours_app.get(
        "/api/v1/scheduler/hours-client/queue",
        params={"scheduled_from": "not-a-date"},
    )
    assert response.status_code == 422


async def test_list_queue_invalid_scheduled_to_returns_422(hours_app: AsyncClient):
    """GET queue with invalid scheduled_to returns 422, not 500."""
    response = await hours_app.get(
        "/api/v1/scheduler/hours-client/queue",
        params={"scheduled_to": "definitely-not-a-datetime"},
    )
    assert response.status_code == 422


async def test_list_queue_valid_date_filter_returns_200(hours_app: AsyncClient):
    """GET queue with valid ISO datetime filters returns 200."""
    response = await hours_app.get(
        "/api/v1/clients/hours-client/scheduled-calls",
        params={
            "scheduled_from": "2026-06-01T00:00:00+00:00",
            "scheduled_to": "2026-06-30T23:59:59+00:00",
        },
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)


# ---------------------------------------------------------------------------
# Issue 5: Naive datetime treated as UTC in schedule_followup
# ---------------------------------------------------------------------------


async def test_schedule_followup_date_only_interpreted_as_local_tz(followup_app):
    """Date-only strings must be interpreted as client local TZ (Buenos Aires = UTC-3).

    "2026-06-01" at local start_hour=9 in Buenos Aires (UTC-3) = 12:00 UTC.
    The scheduled_at stored must be 12:00 UTC, NOT 00:00 UTC.
    """
    from app.tools.schedule_followup import schedule_followup
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select

    async with followup_app.async_session_factory() as sess:
        result = await schedule_followup(
            session=sess,
            lead_id="fu-lead-001",
            followup_date="2026-06-01",
            note=None,
            client_id="fu-client",
            source_session_id=None,
        )
        await sess.commit()

    assert "error" not in result
    assert result.get("scheduled_call_created") is True

    # Verify the scheduled_at is in local time (not UTC midnight)
    async with followup_app.async_session_factory() as sess:
        rows = await sess.execute(
            select(ScheduledCall).where(ScheduledCall.lead_id == "fu-lead-001")
        )
        sc = rows.scalar_one()
        # Buenos Aires is UTC-3; 09:00 local = 12:00 UTC
        # The call must NOT be at 00:00 UTC (which is what naive UTC interpretation would give)
        sc_utc = (
            sc.scheduled_at.replace(tzinfo=timezone.utc)
            if sc.scheduled_at.tzinfo is None
            else sc.scheduled_at.astimezone(timezone.utc)
        )
        assert sc_utc.hour != 0, (
            f"scheduled_at {sc_utc} looks like UTC midnight — "
            "date-only strings must be interpreted as local TZ start_hour, not UTC midnight"
        )
        # Should be at 12:00 UTC (09:00 Buenos Aires)
        assert (
            sc_utc.hour == 12
        ), f"Expected 12:00 UTC (09:00 BsAs), got {sc_utc.hour}:00 UTC"


async def test_schedule_followup_naive_datetime_interpreted_as_local_tz(followup_app):
    """Naive datetime strings must be interpreted as client local TZ.

    "2026-06-01T14:00:00" at Buenos Aires (UTC-3) = 17:00 UTC.
    """
    from app.tools.schedule_followup import schedule_followup
    from app.scheduler.models import ScheduledCall
    from sqlalchemy import select

    async with followup_app.async_session_factory() as sess:
        result = await schedule_followup(
            session=sess,
            lead_id="fu-lead-001",
            followup_date="2026-06-01T14:00:00",
            note=None,
            client_id="fu-client",
            source_session_id=None,
        )
        await sess.commit()

    assert "error" not in result
    assert result.get("scheduled_call_created") is True

    async with followup_app.async_session_factory() as sess:
        rows = await sess.execute(
            select(ScheduledCall).where(ScheduledCall.lead_id == "fu-lead-001")
        )
        sc = rows.scalar_one()
        sc_utc = (
            sc.scheduled_at.replace(tzinfo=timezone.utc)
            if sc.scheduled_at.tzinfo is None
            else sc.scheduled_at.astimezone(timezone.utc)
        )
        # 14:00 Buenos Aires (UTC-3) = 17:00 UTC
        assert sc_utc.hour == 17, (
            f"Expected 17:00 UTC (14:00 BsAs), got {sc_utc.hour}:00 UTC — "
            "naive datetimes must be treated as local TZ, not UTC"
        )


# ---------------------------------------------------------------------------
# Issue 6: Naive datetimes in schema
# ---------------------------------------------------------------------------


async def test_create_scheduled_call_naive_datetime_rejected(hours_app: AsyncClient):
    """POST with naive datetime (no timezone) must be rejected with 422."""
    # Naive ISO datetime — no timezone offset
    naive_dt = "2026-06-01T15:00:00"
    response = await hours_app.post(
        "/api/v1/scheduler/hours-client/queue",
        json={"lead_id": "hours-lead-001", "scheduled_at": naive_dt},
    )
    assert response.status_code == 422


async def test_reschedule_naive_datetime_rejected(hours_app: AsyncClient):
    """PATCH reschedule with naive datetime must be rejected with 422."""
    # First create a valid one
    valid_dt = datetime(2026, 6, 1, 18, 0, 0, tzinfo=timezone.utc).isoformat()
    create_resp = await hours_app.post(
        "/api/v1/scheduler/hours-client/queue",
        json={"lead_id": "hours-lead-001", "scheduled_at": valid_dt},
    )
    assert create_resp.status_code == 201
    sc_id = create_resp.json()["id"]

    # Reschedule with naive
    naive_dt = "2026-06-02T15:00:00"
    response = await hours_app.patch(
        f"/api/v1/scheduler/hours-client/queue/{sc_id}",
        json={"scheduled_at": naive_dt},
    )
    assert response.status_code == 422
