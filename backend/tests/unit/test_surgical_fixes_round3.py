"""Surgical fix tests — Round 3 (confirmed issues for feat/10-admin-crud).

Covers:
1. (Removed) XSS tests for admin.html — migrated to React in Issue #29.
2. WARNING — ClientCreate missing validate_hour_window (start < end).
3. WARNING — POST /api/v1/clients duplicate name (Client.name unique) → 409.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def clients_app(tmp_path: Path):
    """Isolated FastAPI app with clients router + fresh SQLite DB."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/r3_clients_test.db",
    )
    await db_module.init_db(settings)

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
# Issue 2 — ClientCreate must validate hour window (start < end)
# ---------------------------------------------------------------------------


async def test_create_client_inverted_hour_window_returns_422(
    clients_app: AsyncClient,
):
    """POST /api/v1/clients with start=22, end=10 must return 422.

    ClientCreate.validate_hour_window was NOT in _SchedulerValidatorMixin,
    so inverted hour windows passed silently.
    """
    resp = await clients_app.post(
        "/api/v1/clients",
        json={
            "client_id": "hour-window-test",
            "name": "Hour Window Test",
            "voice_id": "v1",
            "scheduler_allowed_hours_start": 22,
            "scheduler_allowed_hours_end": 10,
        },
    )
    assert resp.status_code == 422, (
        f"POST /clients with start=22, end=10 must return 422 (invalid hour window). "
        f"Got {resp.status_code}. ClientCreate must validate start < end."
    )


def test_client_create_schema_rejects_inverted_window_directly():
    """ClientCreate pydantic model must raise ValidationError for start >= end."""
    from pydantic import ValidationError
    from app.clients.schemas import ClientCreate

    with pytest.raises(ValidationError) as exc_info:
        ClientCreate(
            client_id="test-client",
            name="Test",
            voice_id="v1",
            scheduler_allowed_hours_start=22,
            scheduler_allowed_hours_end=10,
        )
    errors = exc_info.value.errors()
    assert len(errors) >= 1, "ValidationError must contain at least one error."
    # Check the error is about hour window, not something else
    error_msgs = " ".join(str(e) for e in errors)
    assert (
        "hour" in error_msgs.lower() or "scheduler" in error_msgs.lower()
    ), f"Expected hour window validation error, got: {error_msgs}"


# Triangulation: valid window (start < end) passes
async def test_create_client_valid_hour_window_returns_201(clients_app: AsyncClient):
    """POST /api/v1/clients with valid hour window (start=8, end=18) must return 201."""
    resp = await clients_app.post(
        "/api/v1/clients",
        json={
            "client_id": "valid-hour-window",
            "name": "Valid Hour Window",
            "voice_id": "v1",
            "scheduler_allowed_hours_start": 8,
            "scheduler_allowed_hours_end": 18,
        },
    )
    assert resp.status_code == 201, (
        f"POST /clients with valid hour window (8, 18) must return 201. "
        f"Got {resp.status_code}."
    )


def test_client_create_schema_equal_hours_rejected():
    """ClientCreate must reject start == end (not strictly less than)."""
    from pydantic import ValidationError
    from app.clients.schemas import ClientCreate

    with pytest.raises(ValidationError):
        ClientCreate(
            client_id="test-equal",
            name="Test Equal",
            voice_id="v1",
            scheduler_allowed_hours_start=10,
            scheduler_allowed_hours_end=10,
        )


# ---------------------------------------------------------------------------
# Issue 3 — Duplicate name (Client.name unique) → 409 not 500
# ---------------------------------------------------------------------------


async def test_create_two_clients_same_name_returns_409(
    clients_app: AsyncClient,
):
    """POST /api/v1/clients with duplicate name (same Client.name) → 409.

    Client.name has unique=True in DB. Creating two clients with same name
    but different client_id triggers IntegrityError → must return 409, not 500.
    """
    # First client succeeds
    r1 = await clients_app.post(
        "/api/v1/clients",
        json={
            "client_id": "broker-alpha",
            "name": "Duplicate Broker",
            "voice_id": "v1",
        },
    )
    assert (
        r1.status_code == 201
    ), f"First client creation must succeed. Got {r1.status_code}."

    # Second client with same name but different client_id → 409
    r2 = await clients_app.post(
        "/api/v1/clients",
        json={
            "client_id": "broker-beta",
            "name": "Duplicate Broker",  # same name → same Client.name
            "voice_id": "v1",
        },
    )
    assert r2.status_code == 409, (
        f"POST /clients with duplicate name must return 409 (not 500 IntegrityError). "
        f"Got {r2.status_code}. Router must catch IntegrityError from Client.name unique constraint."
    )


# Triangulation: different broker names succeed independently
async def test_create_two_clients_different_names_succeed(
    clients_app: AsyncClient,
):
    """POST /api/v1/clients with distinct names → both 201."""
    r1 = await clients_app.post(
        "/api/v1/clients",
        json={
            "client_id": "unique-alpha",
            "name": "Alpha Broker",
            "voice_id": "v1",
        },
    )
    r2 = await clients_app.post(
        "/api/v1/clients",
        json={
            "client_id": "unique-beta",
            "name": "Beta Broker",
            "voice_id": "v1",
        },
    )
    assert r1.status_code == 201
    assert r2.status_code == 201
