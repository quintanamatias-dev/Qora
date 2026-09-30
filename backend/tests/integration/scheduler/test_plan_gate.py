"""Integration test: scheduler plan gate blocks dial without creating a session."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest_asyncio
import structlog.testing
from pydantic import SecretStr
from sqlalchemy import select

from app.scheduler.service import create_scheduled_call, run_scheduler_cycle

_IN_WINDOW_UTC = datetime(
    2026, 7, 20, 17, 0, tzinfo=timezone.utc
)  # inside default allowed hours (F2)


@pytest_asyncio.fixture
async def tick_db(tmp_path: Path):
    """DB with quintana + test lead for tick tests."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/scheduler_plan_gate_test.db",
    )
    from tests.helpers.migrations import (
        init_db_with_migrations as _init_db_with_migrations,
    )

    await _init_db_with_migrations(db_module, settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead

        await seed_quintana(sess)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Tick Test Lead",
            phone="+5491100000001",
            lead_id="tick-lead-001",
        )
        await sess.commit()

    yield db_module
    await db_module.close_db()


def _auto_dialer_settings(tmp_path_db_url: str, *, enable_auto_dialer: bool):
    from app.core.config import Settings

    return Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=tmp_path_db_url,
        enable_auto_dialer=enable_auto_dialer,
        enable_outbound_calls=enable_auto_dialer,
        qora_webhook_auth_enabled=enable_auto_dialer,
        qora_webhook_secret=SecretStr("test-webhook-secret")
        if enable_auto_dialer
        else None,
        auto_dialer_max_concurrent_dials=1,
    )


async def _mk_call(sess, lead_id, scheduled_at, **overrides):
    kwargs = dict(
        client_id="quintana-seguros",
        lead_id=lead_id,
        scheduled_at=scheduled_at,
        trigger_reason="manual",
        source_session_id=None,
        attempt_number=1,
        max_attempts=3,
        notes=None,
    )
    kwargs.update(overrides)
    return await create_scheduled_call(sess, **kwargs)


async def test_scheduler_cycle_plan_block_fails_row_and_logs_code(tick_db):
    """A real plan gate blocks the tick without creating a session or calling a provider."""
    from app.calls.models import CallSession
    from app.elevenlabs.service import ElevenLabsService
    from app.scheduler.models import ScheduledCall
    from app.tenants.models import Client

    async with tick_db.async_session_factory() as sess:
        client = await sess.get(Client, "quintana-seguros")
        client.plan = "starter"  # auto_dialer disabled
        sc = await _mk_call(
            sess, "tick-lead-001", _IN_WINDOW_UTC - timedelta(minutes=1)
        )
        await sess.commit()
        sc_id = sc.id

    settings = _auto_dialer_settings(
        "sqlite+aiosqlite:///unused", enable_auto_dialer=True
    )
    with (
        patch.object(
            ElevenLabsService, "initiate_outbound_call", AsyncMock()
        ) as provider,
        structlog.testing.capture_logs() as logs,
    ):
        async with tick_db.async_session_factory() as sess:
            await run_scheduler_cycle(sess, settings, now_utc=_IN_WINDOW_UTC)

    provider.assert_not_called()
    assert any(
        entry.get("event") == "auto_dialer_dial_failed"
        and entry.get("failure_code") == "plan_feature_disabled"
        and entry.get("scheduled_call_id") == sc_id
        for entry in logs
    )
    async with tick_db.async_session_factory() as sess:
        row = await sess.get(ScheduledCall, sc_id)
        sessions = (await sess.execute(select(CallSession))).scalars().all()
        assert row.status == "failed"
        assert sessions == []
