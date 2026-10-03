"""Tasks 4.3, 5.4 — POST /api/v1/admin/onboarding, superadmin-gated, and
CLI/endpoint parity."""

from __future__ import annotations

from pathlib import Path

import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


def _spec_payload(**overrides):
    base = dict(
        client_id="acme",
        client_name="Acme Co",
        client_language="Spanish",
        agent_slug="jaumpablo",
        agent_name="Jaumpablo",
        agent_goal="Sell insurance",
        agent_system_prompt="You are a helpful agent.",
        agent_voice_id="voice-1",
    )
    base.update(overrides)
    return base


@pytest_asyncio.fixture
async def onboarding_app(tmp_path: Path):
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/onboarding_router_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations

    await init_db_with_migrations(db_module, settings)

    from app.onboarding.router import router as onboarding_router

    test_app = FastAPI()
    test_app.state.settings = settings
    test_app.include_router(onboarding_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        yield client, test_app

    await db_module.close_db()


async def test_post_onboarding_requires_superadmin(onboarding_app):
    from app.core.auth import CallerIdentity, require_api_key

    client, app = onboarding_app
    app.dependency_overrides[require_api_key] = lambda: CallerIdentity(
        api_key_hash="t", role="client", client_ids=frozenset({"acme"})
    )

    response = await client.post(
        "/api/v1/admin/onboarding",
        json={"spec": _spec_payload(), "dry_run": True},
    )
    assert response.status_code == 403
    app.dependency_overrides.clear()


async def test_post_onboarding_dry_run_via_endpoint(onboarding_app):
    client, _app = onboarding_app
    response = await client.post(
        "/api/v1/admin/onboarding",
        json={"spec": _spec_payload(), "dry_run": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["conflicts"] == []


async def test_cli_and_endpoint_produce_identical_results(onboarding_app, tmp_path: Path):
    from app.core import database as db_module
    from app.onboarding.service import run_onboarding
    from app.onboarding.spec import OnboardingSpec

    client, _app = onboarding_app
    payload = _spec_payload(client_id="parity-client", client_name="Parity Co")

    async with db_module.async_session_factory() as session:
        cli_result = await run_onboarding(
            OnboardingSpec(**payload), session, dry_run=True
        )
        await session.commit()

    response = await client.post(
        "/api/v1/admin/onboarding",
        json={"spec": payload, "dry_run": True},
    )
    endpoint_result = response.json()

    assert endpoint_result["dry_run"] == cli_result.dry_run
    assert endpoint_result["conflicts"] == cli_result.conflicts
