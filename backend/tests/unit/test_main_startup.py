"""Task 6.3 — app starts successfully with a degraded client in the DB.

Smoke test for client-integrations-secrets Phase 6: the real lifespan
(including the real, unmocked validate_all_integration_credentials call)
must let TestClient construction succeed even when a seeded client_integrations
row has an unresolvable credential. No import-time or startup-event code path
may still assume the old sys.exit-or-success binary outcome.

Design: openspec/changes/client-integrations-secrets/design.md P3-D4.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from pydantic import SecretStr


async def test_app_starts_with_degraded_client_in_db(tmp_path: Path, monkeypatch):
    from app.core.config import Settings
    from app.core import database as db_module
    from tests.helpers.migrations import init_db_with_migrations

    db_url = f"sqlite+aiosqlite:///{tmp_path}/main_startup_test.db"
    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=db_url,
    )
    await init_db_with_migrations(db_module, settings)

    async with db_module.async_session_factory() as session:
        from app.tenants.service import seed_quintana

        await seed_quintana(session)
        await session.commit()

    async with db_module.async_session_factory() as session:
        from app.tenants.models import ClientIntegration

        row = ClientIntegration(
            client_id="quintana-seguros",
            provider="airtable",
            enabled=True,
            config=json.dumps({
                "base_id": "appXXXXXXXXXXXXXX",
                "table_id": "tblYYYYYYYYYYYYYY",
                "match_field": "phone",
                "field_mappings": [],
                "legacy_env_var_name": "TOTALLY_UNSET_ENV_VAR_FOR_SMOKE_TEST",
            }),
            status="ok",
            created_by="test",
            updated_by="test",
        )
        session.add(row)
        await session.commit()

    await db_module.close_db()

    monkeypatch.delenv("TOTALLY_UNSET_ENV_VAR_FOR_SMOKE_TEST", raising=False)

    from fastapi import FastAPI

    from app.main import lifespan

    mini_app = FastAPI(lifespan=lifespan)

    with (
        patch("app.main.Settings", return_value=settings),
        patch("app.main.setup_logging"),
        patch("app.tenants.service.seed_quintana", new_callable=AsyncMock),
        patch("app.leads.service.seed_leads", new_callable=AsyncMock),
        patch("app.sweeper.stale_session_sweeper", new_callable=AsyncMock),
        patch("app.scheduler.service.scheduler_tick", new_callable=AsyncMock),
    ):
        from starlette.testclient import TestClient

        # The real (unmocked) validate_all_integration_credentials runs here.
        # TestClient construction (entering the context manager) must succeed
        # even though the seeded row's credential cannot resolve.
        with TestClient(mini_app):
            pass

    await db_module.init_db(settings)
    try:
        from sqlalchemy import select

        from app.tenants.models import ClientIntegration

        async with db_module.async_session_factory() as session:
            result = await session.execute(
                select(ClientIntegration).where(ClientIntegration.client_id == "quintana-seguros")
            )
            persisted_row = result.scalar_one()
            assert persisted_row.status == "degraded"
            assert persisted_row.status_reason is not None
    finally:
        await db_module.close_db()
