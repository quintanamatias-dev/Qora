"""Usage counters and the plan gate inside dial_outbound_call (multi-tenant-readiness WU2).

Spec: openspec/changes/multi-tenant-readiness/specs/plan-entitlements/spec.md
      Requirement: Outbound Usage Limits
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from app.entitlements.service import check_dial_allowed, get_usage, month_start_utc

TZ = "America/Argentina/Buenos_Aires"


async def _client(db, *, plan="starter", overrides=None, client_id="acme"):
    from app.tenants.service import create_client

    client = await create_client(db, id=client_id, name=f"Client {client_id}", voice_id="v")
    client.plan = plan
    client.entitlement_overrides = json.dumps(overrides) if overrides else None
    client.scheduler_timezone = TZ
    await db.flush()
    return client


def _session(client_id, *, started_at, duration=None, telephony_status=None, status="completed"):
    from app.calls.models import CallSession

    return CallSession(
        id=str(uuid.uuid4()),
        client_id=client_id,
        lead_id=None,
        status=status,
        started_at=started_at,
        duration_seconds=duration,
        telephony_status=telephony_status,
    )


class TestMonthStart:
    def test_month_start_uses_client_timezone(self):
        # 2026-10-01 01:00 UTC is still September 30 in Buenos Aires (UTC-3).
        now = datetime(2026, 10, 1, 1, 0, tzinfo=timezone.utc)
        assert month_start_utc(TZ, now) == datetime(2026, 9, 1, 3, 0, tzinfo=timezone.utc)

    def test_unknown_timezone_falls_back_to_utc(self):
        now = datetime(2026, 9, 15, tzinfo=timezone.utc)
        assert month_start_utc("Mars/Olympus", now) == datetime(2026, 9, 1, tzinfo=timezone.utc)


class TestUsage:
    async def test_counts_only_this_month_real_calls(self, db_session):
        client = await _client(db_session)
        now = datetime.now(timezone.utc)
        db_session.add_all(
            [
                _session("acme", started_at=now, duration=90),  # 1.5 min
                _session("acme", started_at=now, duration=30, telephony_status="completed"),
                _session("acme", started_at=now, status="initiated"),  # ghost: never a call
                _session("acme", started_at=month_start_utc(TZ) - timedelta(days=2), duration=600),
            ]
        )
        await db_session.flush()

        usage = await get_usage(db_session, client)
        assert usage.monthly_calls == 2
        assert usage.monthly_minutes == 2  # ceil(120s / 60)

    async def test_isolated_per_client(self, db_session):
        await _client(db_session)
        other = await _client(db_session, client_id="other")
        db_session.add(_session("acme", started_at=datetime.now(timezone.utc), duration=600))
        await db_session.flush()

        usage = await get_usage(db_session, other)
        assert usage.monthly_calls == 0
        assert usage.monthly_minutes == 0

    async def test_counts_active_agents_and_concurrent_calls(self, db_session):
        client = await _client(db_session)
        db_session.add(_session("acme", started_at=datetime.now(timezone.utc), telephony_status="ringing", status="initiated"))
        await db_session.flush()

        usage = await get_usage(db_session, client)
        assert usage.concurrent_calls == 1
        assert usage.active_agents >= 0


class TestCheckDialAllowed:
    async def test_pilot_is_never_blocked(self, db_session):
        client = await _client(db_session, plan="pilot")
        assert await check_dial_allowed(db_session, client, scheduled=True) is None

    async def test_scheduled_dial_requires_auto_dialer(self, db_session):
        client = await _client(db_session, plan="starter")
        block = await check_dial_allowed(db_session, client, scheduled=True)
        assert block.failure_code == "plan_feature_disabled"
        assert block.detail == "auto_dialer"

    async def test_manual_dial_blocked_when_minutes_exhausted(self, db_session):
        client = await _client(db_session, plan="starter", overrides={"limits": {"max_monthly_minutes": 2}})
        db_session.add(_session("acme", started_at=datetime.now(timezone.utc), duration=120))
        await db_session.flush()

        block = await check_dial_allowed(db_session, client, scheduled=False)
        assert block.failure_code == "plan_limit_reached"
        assert block.detail == "max_monthly_minutes"

    async def test_concurrent_limit(self, db_session):
        client = await _client(db_session, plan="starter")  # max_concurrent_calls = 1
        db_session.add(_session("acme", started_at=datetime.now(timezone.utc), telephony_status="connected", status="initiated"))
        await db_session.flush()

        block = await check_dial_allowed(db_session, client, scheduled=False)
        assert block.detail == "max_concurrent_calls"

    async def test_monthly_calls_limit(self, db_session):
        client = await _client(db_session, plan="pro", overrides={"limits": {"max_monthly_calls": 1}})
        db_session.add(_session("acme", started_at=datetime.now(timezone.utc), duration=10))
        await db_session.flush()

        block = await check_dial_allowed(db_session, client, scheduled=False)
        assert block.detail == "max_monthly_calls"

    async def test_under_limits_is_allowed(self, db_session):
        client = await _client(db_session, plan="starter")
        assert await check_dial_allowed(db_session, client, scheduled=False) is None


class TestDialOutboundCallPlanGate:
    """A blocked dial creates no CallSession and never reaches the provider."""

    async def _dial(self, db, client, *, scheduled_call=None):
        from app.leads.service import create_lead
        from app.outbound.service import dial_outbound_call

        lead = await create_lead(db, client_id=client.id, name="Lead", phone="+5491122223333")
        agent = MagicMock()
        agent.id = "agent-1"
        agent.client_id = client.id
        agent.elevenlabs_agent_id = "el-agent"
        agent.elevenlabs_phone_number_id = "pn-1"
        settings = MagicMock()
        settings.enable_outbound_calls = True
        settings.elevenlabs_api_key = SecretStr("k")
        with patch("app.outbound.service.ElevenLabsService") as provider:
            result = await dial_outbound_call(
                db, lead=lead, agent=agent, client=client, settings=settings, scheduled_call=scheduled_call
            )
        return result, provider

    async def _session_count(self, db):
        from app.calls.models import CallSession

        return (await db.execute(select(func.count(CallSession.id)))).scalar_one()

    async def test_manual_dial_blocked_by_feature(self, db_session):
        client = await _client(db_session, plan="starter", overrides={"features": {"outbound_calls": False}})
        result, provider = await self._dial(db_session, client)

        assert result.status == "failed"
        assert result.failure_code == "plan_feature_disabled"
        assert await self._session_count(db_session) == 0
        provider.assert_not_called()

    async def test_scheduled_dial_blocked_without_auto_dialer(self, db_session):
        client = await _client(db_session, plan="starter")
        result, provider = await self._dial(db_session, client, scheduled_call=MagicMock(id="sc-1"))

        assert result.failure_code == "plan_feature_disabled"
        assert await self._session_count(db_session) == 0
        provider.assert_not_called()

    async def test_dial_blocked_by_monthly_minutes(self, db_session):
        client = await _client(db_session, plan="starter", overrides={"limits": {"max_monthly_minutes": 1}})
        db_session.add(_session("acme", started_at=datetime.now(timezone.utc), duration=60))
        await db_session.flush()

        result, provider = await self._dial(db_session, client)
        assert result.failure_code == "plan_limit_reached"
        assert await self._session_count(db_session) == 1  # only the pre-existing one
        provider.assert_not_called()
