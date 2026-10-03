"""Unit tests for the ElevenLabs reconciler — fetch-only drift detection.

Spec: openspec/changes/elevenlabs-reconciler/design.md — R-D1, R-D2, Interfaces/Contracts.

Covers:
- Task 2.1: build_config_payload is importable and identical to the save path's helper.
- Task 2.2: run_reconciliation_once upserts in_sync / drift reports; never issues a PATCH.
- Task 2.3: a single agent's fetch error is isolated and does not block sibling agents.
- Task 3.1: reconciler_tick survives an unhandled exception in run_reconciliation_once.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(api_key: str | None = "test-xi-api-key"):
    settings = MagicMock()
    settings.elevenlabs_api_key = SecretStr(api_key) if api_key else None
    settings.public_base_url = None
    settings.elevenlabs_reconciler_interval_hours = 6
    return settings


@pytest_asyncio.fixture
async def db_session(tmp_path):
    from app.core.config import Settings
    from app.core import database as db_module
    from tests.helpers.migrations import init_db_with_migrations

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/reconciler_test.db",
    )
    await init_db_with_migrations(db_module, settings)

    try:
        async with db_module.async_session_factory() as session:
            yield session
    finally:
        await db_module.close_db()


async def _make_client_and_agent(
    session,
    *,
    client_id: str = "test-client",
    agent_id: str = "agent-1",
    elevenlabs_agent_id: str | None = "el-agent-1",
    is_active: bool = True,
):
    from app.tenants.models import Agent, Client

    client = Client(id=client_id, name=client_id, voice_id="voice-1")
    session.add(client)
    agent = Agent(
        id=agent_id,
        client_id=client_id,
        slug="main",
        name="Main Agent",
        voice_id="voice-1",
        elevenlabs_agent_id=elevenlabs_agent_id,
        is_active=is_active,
        tts_speed=0.95,
        tts_stability=0.4,
        tts_similarity_boost=0.75,
        tts_model="eleven_v4_turbo",
    )
    session.add(agent)
    await session.commit()
    return agent


def test_build_config_payload_is_importable_and_reused_by_save_path():
    """build_config_payload must be a public, importable name from app.elevenlabs.service,
    and it must be the exact function sync_agent_config's save path already uses
    internally (no reimplementation in the reconciler)."""
    from app.elevenlabs import service as service_module
    from app.elevenlabs.service import build_config_payload

    assert callable(build_config_payload)
    # The private name (used by existing tests/call sites) must remain the same
    # function object — a behavioral no-op extraction, not a rename-and-diverge.
    assert service_module._build_config_payload is build_config_payload


# ---------------------------------------------------------------------------
# Task 2.2 — run_reconciliation_once
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_reconciliation_once_upserts_in_sync_report(db_session):
    from app.elevenlabs.reconciler import run_reconciliation_once
    from app.elevenlabs.models import ElevenLabsReconciliationReport
    from sqlalchemy import select

    agent = await _make_client_and_agent(db_session)
    settings = _make_settings()

    # Live config matches the agent's TTS defaults exactly (the only block
    # build_config_payload always sends for a real Agent row).
    matching_actual = {
        "conversation_config": {
            "tts": {
                "voice_id": "voice-1",
                "model_id": "eleven_v4_turbo",
                "speed": 0.95,
                "stability": 0.4,
                "similarity_boost": 0.75,
            }
        }
    }
    with patch(
        "app.elevenlabs.reconciler._fetch_agent_config",
        new=AsyncMock(return_value=matching_actual),
    ):
        await run_reconciliation_once(db_session, settings)

    result = await db_session.execute(
        select(ElevenLabsReconciliationReport).where(
            ElevenLabsReconciliationReport.agent_id == agent.id
        )
    )
    report = result.scalar_one()
    assert report.status == "in_sync"
    assert report.client_id == agent.client_id


@pytest.mark.asyncio
async def test_run_reconciliation_once_upserts_drift_report(db_session):
    from app.elevenlabs.reconciler import run_reconciliation_once
    from app.elevenlabs.models import ElevenLabsReconciliationReport
    from sqlalchemy import select

    agent = await _make_client_and_agent(db_session)
    agent.max_call_duration_seconds = 120
    await db_session.commit()
    settings = _make_settings()

    # Live config reports a different max_duration_seconds than the projection sent.
    with patch(
        "app.elevenlabs.reconciler._fetch_agent_config",
        new=AsyncMock(
            return_value={
                "conversation_config": {"conversation": {"max_duration_seconds": 999}}
            }
        ),
    ):
        await run_reconciliation_once(db_session, settings)

    result = await db_session.execute(
        select(ElevenLabsReconciliationReport).where(
            ElevenLabsReconciliationReport.agent_id == agent.id
        )
    )
    report = result.scalar_one()
    assert report.status == "drift"
    assert "conversation_config.conversation.max_duration_seconds" in report.drift_fields


@pytest.mark.asyncio
async def test_run_reconciliation_once_never_issues_patch(db_session):
    """The reconciler must only ever GET the live config — never PATCH/PUT/POST."""
    import httpx
    import respx

    from app.elevenlabs.reconciler import run_reconciliation_once

    await _make_client_and_agent(db_session)
    settings = _make_settings()

    with respx.mock(assert_all_mocked=False, assert_all_called=False) as respx_mock:
        get_route = respx_mock.get(url__regex=r".*").mock(
            return_value=httpx.Response(200, json={"conversation_config": {}})
        )
        patch_route = respx_mock.patch(url__regex=r".*")
        put_route = respx_mock.put(url__regex=r".*")
        post_route = respx_mock.post(url__regex=r".*")

        await run_reconciliation_once(db_session, settings)

        assert get_route.called
        assert not patch_route.called
        assert not put_route.called
        assert not post_route.called


@pytest.mark.asyncio
async def test_run_reconciliation_once_skips_when_api_key_missing(db_session):
    from app.elevenlabs.reconciler import run_reconciliation_once
    from app.elevenlabs.models import ElevenLabsReconciliationReport
    from sqlalchemy import select

    await _make_client_and_agent(db_session)
    settings = _make_settings(api_key=None)

    with patch(
        "app.elevenlabs.reconciler._fetch_agent_config",
        new=AsyncMock(return_value={"conversation_config": {}}),
    ) as fetch_mock:
        await run_reconciliation_once(db_session, settings)
        fetch_mock.assert_not_called()

    result = await db_session.execute(select(ElevenLabsReconciliationReport))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_one_agent_fetch_error_does_not_block_sibling_agent_isolation(db_session):
    from app.elevenlabs.reconciler import run_reconciliation_once
    from app.elevenlabs.models import ElevenLabsReconciliationReport
    from sqlalchemy import select

    failing_agent = await _make_client_and_agent(
        db_session, client_id="client-a", agent_id="agent-a", elevenlabs_agent_id="el-a"
    )
    healthy_agent = await _make_client_and_agent(
        db_session, client_id="client-b", agent_id="agent-b", elevenlabs_agent_id="el-b"
    )
    settings = _make_settings()

    matching_actual = {
        "conversation_config": {
            "tts": {
                "voice_id": "voice-1",
                "model_id": "eleven_v4_turbo",
                "speed": 0.95,
                "stability": 0.4,
                "similarity_boost": 0.75,
            }
        }
    }

    async def _fetch_side_effect(url, headers, elevenlabs_agent_id):
        if elevenlabs_agent_id == "el-a":
            raise RuntimeError("simulated fetch failure")
        return matching_actual

    with patch(
        "app.elevenlabs.reconciler._fetch_agent_config",
        new=AsyncMock(side_effect=_fetch_side_effect),
    ):
        await run_reconciliation_once(db_session, settings)

    result = await db_session.execute(select(ElevenLabsReconciliationReport))
    reports = {r.agent_id: r for r in result.scalars().all()}
    assert reports[failing_agent.id].status == "error"
    assert reports[healthy_agent.id].status == "in_sync"


# ---------------------------------------------------------------------------
# Gap — custom_llm.url drift reporting when PUBLIC_BASE_URL is set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_reconciliation_once_reports_custom_llm_url_drift(db_session):
    """When PUBLIC_BASE_URL is set and the live agent uses llm=custom-llm, the
    projection must include the expected agent-scoped custom_llm.url so a stale
    live URL is reported as drift — comparing only url, never secrets/headers.
    """
    from app.elevenlabs.reconciler import run_reconciliation_once
    from app.elevenlabs.models import ElevenLabsReconciliationReport
    from sqlalchemy import select

    agent = await _make_client_and_agent(db_session)
    settings = _make_settings()
    settings.public_base_url = "https://qora.example.com"

    matching_actual = {
        "conversation_config": {
            "tts": {
                "voice_id": "voice-1",
                "model_id": "eleven_v4_turbo",
                "speed": 0.95,
                "stability": 0.4,
                "similarity_boost": 0.75,
            },
            "agent": {
                "prompt": {
                    "llm": "custom-llm",
                    "custom_llm": {
                        "url": "https://stale-url.example.com/old-path",
                        "api_key": {"secret_id": "keep-me-untouched"},
                    },
                }
            },
        }
    }
    with patch(
        "app.elevenlabs.reconciler._fetch_agent_config",
        new=AsyncMock(return_value=matching_actual),
    ):
        await run_reconciliation_once(db_session, settings)

    result = await db_session.execute(
        select(ElevenLabsReconciliationReport).where(
            ElevenLabsReconciliationReport.agent_id == agent.id
        )
    )
    report = result.scalar_one()
    assert report.status == "drift"
    assert (
        "conversation_config.agent.prompt.custom_llm.url" in report.drift_fields
    )
    # Only the url leaf is compared — the live secret must never surface as a
    # separately-named drift field.
    assert "custom_llm.api_key" not in report.drift_fields


@pytest.mark.asyncio
async def test_run_reconciliation_once_in_sync_when_custom_llm_url_matches(db_session):
    """No drift when the live custom_llm.url already matches the expected
    agent-scoped URL built from PUBLIC_BASE_URL."""
    from app.elevenlabs.reconciler import run_reconciliation_once
    from app.elevenlabs.models import ElevenLabsReconciliationReport
    from sqlalchemy import select

    agent = await _make_client_and_agent(db_session)
    settings = _make_settings()
    settings.public_base_url = "https://qora.example.com"
    expected_url = f"https://qora.example.com/api/v1/voice/{agent.client_id}/agents/{agent.id}/custom-llm"

    matching_actual = {
        "conversation_config": {
            "tts": {
                "voice_id": "voice-1",
                "model_id": "eleven_v4_turbo",
                "speed": 0.95,
                "stability": 0.4,
                "similarity_boost": 0.75,
            },
            "agent": {
                "prompt": {
                    "llm": "custom-llm",
                    "custom_llm": {"url": expected_url},
                }
            },
        }
    }
    with patch(
        "app.elevenlabs.reconciler._fetch_agent_config",
        new=AsyncMock(return_value=matching_actual),
    ):
        await run_reconciliation_once(db_session, settings)

    result = await db_session.execute(
        select(ElevenLabsReconciliationReport).where(
            ElevenLabsReconciliationReport.agent_id == agent.id
        )
    )
    report = result.scalar_one()
    assert report.status == "in_sync"


# ---------------------------------------------------------------------------
# Task 3.1 — reconciler_tick
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconciler_tick_survives_unexpected_exception():
    """An unhandled exception on one tick must not prevent the next tick from running."""
    from app.elevenlabs import reconciler as reconciler_module

    call_count = 0

    async def _fake_run_once(db, settings):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("simulated unhandled exception")

    sleep_calls = 0

    async def _fake_sleep(seconds):
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 3:
            raise asyncio.CancelledError()

    settings = _make_settings()
    fake_session = MagicMock()

    class _FakeSessionCtx:
        async def __aenter__(self):
            return fake_session

        async def __aexit__(self, *exc):
            return False

    with (
        patch.object(reconciler_module, "run_reconciliation_once", new=_fake_run_once),
        patch("asyncio.sleep", new=_fake_sleep),
        patch("app.core.database.get_session", return_value=_FakeSessionCtx()),
    ):
        try:
            await reconciler_module.reconciler_tick(settings)
        except asyncio.CancelledError:
            pass

    assert call_count == 2, "the second tick must still run after the first raised"
