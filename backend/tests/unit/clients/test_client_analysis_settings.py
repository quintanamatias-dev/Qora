"""PATCH/GET coverage for next-action and analysis-locale client settings.

These columns (app/tenants/models.py ~196-215) are read at runtime by the
post-call pipeline (app/summarizer.py ~443-465) but were previously
unreachable through the clients API:

- next_action_max_attempts (int, default 5)
- next_action_min_interest_for_followup (int, default 40)
- next_action_close_on_hard_rejection (bool, default True)
- analysis_language (str, default "Spanish")

Also covers the scheduler_retry_on_outcomes response default mismatch with
the DB column default.
"""

from __future__ import annotations

from pathlib import Path

import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


@pytest_asyncio.fixture
async def clients_app_seeded(tmp_path: Path):
    """Isolated app with one client pre-seeded (quintana-seguros)."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/clients_analysis_settings_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations
    await _init_db_with_migrations(db_module, settings)

    async with db_module.async_session_factory() as session:
        from app.tenants.service import seed_quintana

        await seed_quintana(session)
        await session.commit()

    from app.clients.router import router as clients_router
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.include_router(clients_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        yield client

    await db_module.close_db()


# ---------------------------------------------------------------------------
# PATCH persists + GET returns each new field
# ---------------------------------------------------------------------------


async def test_patch_persists_next_action_max_attempts(clients_app_seeded: AsyncClient):
    response = await clients_app_seeded.patch(
        "/api/v1/clients/quintana-seguros",
        json={"next_action_max_attempts": 8},
    )
    assert response.status_code == 200
    assert response.json()["next_action_max_attempts"] == 8

    get_resp = await clients_app_seeded.get("/api/v1/clients/quintana-seguros")
    assert get_resp.json()["next_action_max_attempts"] == 8


async def test_patch_persists_next_action_min_interest_for_followup(
    clients_app_seeded: AsyncClient,
):
    response = await clients_app_seeded.patch(
        "/api/v1/clients/quintana-seguros",
        json={"next_action_min_interest_for_followup": 60},
    )
    assert response.status_code == 200
    assert response.json()["next_action_min_interest_for_followup"] == 60

    get_resp = await clients_app_seeded.get("/api/v1/clients/quintana-seguros")
    assert get_resp.json()["next_action_min_interest_for_followup"] == 60


async def test_patch_persists_next_action_close_on_hard_rejection(
    clients_app_seeded: AsyncClient,
):
    response = await clients_app_seeded.patch(
        "/api/v1/clients/quintana-seguros",
        json={"next_action_close_on_hard_rejection": False},
    )
    assert response.status_code == 200
    assert response.json()["next_action_close_on_hard_rejection"] is False

    get_resp = await clients_app_seeded.get("/api/v1/clients/quintana-seguros")
    assert get_resp.json()["next_action_close_on_hard_rejection"] is False


async def test_patch_persists_analysis_language(clients_app_seeded: AsyncClient):
    response = await clients_app_seeded.patch(
        "/api/v1/clients/quintana-seguros",
        json={"analysis_language": "English"},
    )
    assert response.status_code == 200
    assert response.json()["analysis_language"] == "English"

    get_resp = await clients_app_seeded.get("/api/v1/clients/quintana-seguros")
    assert get_resp.json()["analysis_language"] == "English"


# ---------------------------------------------------------------------------
# Untouched fields keep their defaults
# ---------------------------------------------------------------------------


async def test_untouched_fields_keep_defaults(clients_app_seeded: AsyncClient):
    response = await clients_app_seeded.patch(
        "/api/v1/clients/quintana-seguros",
        json={"next_action_max_attempts": 7},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["next_action_min_interest_for_followup"] == 40
    assert data["next_action_close_on_hard_rejection"] is True
    assert data["analysis_language"] == "Spanish"


async def test_get_defaults_match_db_defaults(clients_app_seeded: AsyncClient):
    get_resp = await clients_app_seeded.get("/api/v1/clients/quintana-seguros")
    data = get_resp.json()
    assert data["next_action_max_attempts"] == 5
    assert data["next_action_min_interest_for_followup"] == 40
    assert data["next_action_close_on_hard_rejection"] is True
    assert data["analysis_language"] == "Spanish"


# ---------------------------------------------------------------------------
# scheduler_retry_on_outcomes response default must match the DB default
# ---------------------------------------------------------------------------


def test_client_response_schema_default_matches_db_default():
    from app.clients.schemas import ClientResponse

    default = ClientResponse.model_fields["scheduler_retry_on_outcomes"].default
    assert default == '["follow_up","retry_call","schedule_call"]'


# ---------------------------------------------------------------------------
# Validation: 422 for out-of-range / empty values
# ---------------------------------------------------------------------------


async def test_patch_next_action_max_attempts_below_min_returns_422(
    clients_app_seeded: AsyncClient,
):
    response = await clients_app_seeded.patch(
        "/api/v1/clients/quintana-seguros",
        json={"next_action_max_attempts": 0},
    )
    assert response.status_code == 422


async def test_patch_next_action_max_attempts_above_max_returns_422(
    clients_app_seeded: AsyncClient,
):
    response = await clients_app_seeded.patch(
        "/api/v1/clients/quintana-seguros",
        json={"next_action_max_attempts": 21},
    )
    assert response.status_code == 422


async def test_patch_next_action_min_interest_below_min_returns_422(
    clients_app_seeded: AsyncClient,
):
    response = await clients_app_seeded.patch(
        "/api/v1/clients/quintana-seguros",
        json={"next_action_min_interest_for_followup": -1},
    )
    assert response.status_code == 422


async def test_patch_next_action_min_interest_above_max_returns_422(
    clients_app_seeded: AsyncClient,
):
    response = await clients_app_seeded.patch(
        "/api/v1/clients/quintana-seguros",
        json={"next_action_min_interest_for_followup": 101},
    )
    assert response.status_code == 422


async def test_patch_empty_analysis_language_returns_422(clients_app_seeded: AsyncClient):
    response = await clients_app_seeded.patch(
        "/api/v1/clients/quintana-seguros",
        json={"analysis_language": ""},
    )
    assert response.status_code == 422


async def test_patch_analysis_language_too_long_returns_422(clients_app_seeded: AsyncClient):
    response = await clients_app_seeded.patch(
        "/api/v1/clients/quintana-seguros",
        json={"analysis_language": "x" * 41},
    )
    assert response.status_code == 422


async def test_patch_analysis_language_is_stripped(clients_app_seeded: AsyncClient):
    response = await clients_app_seeded.patch(
        "/api/v1/clients/quintana-seguros",
        json={"analysis_language": "  English  "},
    )
    assert response.status_code == 200
    assert response.json()["analysis_language"] == "English"


# ---------------------------------------------------------------------------
# Non-superadmin PATCH still 403
# ---------------------------------------------------------------------------


async def test_patch_non_superadmin_returns_403(tmp_path: Path):
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/clients_analysis_settings_403_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations
    await _init_db_with_migrations(db_module, settings)

    async with db_module.async_session_factory() as session:
        from app.tenants.service import seed_quintana

        await seed_quintana(session)
        await session.commit()

    from app.clients.router import router as clients_router
    from app.core.auth import require_api_key, CallerIdentity
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.include_router(clients_router, prefix="/api/v1")
    test_app.dependency_overrides[require_api_key] = lambda: CallerIdentity(
        api_key_hash="client-test",
        role="client",
        client_ids=frozenset({"quintana-seguros"}),
    )

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        response = await client.patch(
            "/api/v1/clients/quintana-seguros",
            json={"next_action_max_attempts": 8},
        )
        assert response.status_code == 403

    await db_module.close_db()
