"""Unit/integration tests for the clients CRUD router.

Tests cover:
- POST /api/v1/clients → 201 with new client
- POST /api/v1/clients with duplicate id → 409 Conflict
- POST /api/v1/clients with invalid slug → 422
- GET /api/v1/clients → list of active clients
- GET /api/v1/clients/{id} → single client
- GET /api/v1/clients/{id} not found → 404
- PATCH /api/v1/clients/{id} → updated client
- DELETE /api/v1/clients/{id} → soft delete (is_active=False)
- DELETE /api/v1/clients/{id} not found → 404

Covers: T3.1 — CAP-3 Client CRUD API
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
        database_url=f"sqlite+aiosqlite:///{tmp_path}/clients_router_test.db",
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


@pytest_asyncio.fixture
async def clients_app_seeded(tmp_path: Path):
    """Isolated app with one client pre-seeded (quintana-seguros)."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/clients_seeded_test.db",
    )
    await db_module.init_db(settings)

    # Pre-seed one client
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
# POST /api/v1/clients
# ---------------------------------------------------------------------------


async def test_create_client_returns_201(clients_app: AsyncClient):
    """POST /clients with valid payload returns 201 with created client."""
    response = await clients_app.post(
        "/api/v1/clients",
        json={
            "client_id": "new-broker",
            "broker_name": "New Broker SA",
            "agent_name": "Ana",
            "voice_id": "abc123",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["client_id"] == "new-broker"
    assert data["broker_name"] == "New Broker SA"
    assert data["agent_name"] == "Ana"
    assert data["voice_id"] == "abc123"
    assert data["is_active"] is True
    assert "created_at" in data


async def test_create_client_default_agent_name(clients_app: AsyncClient):
    """POST /clients without agent_name uses default 'Jaumpablo'."""
    response = await clients_app.post(
        "/api/v1/clients",
        json={
            "client_id": "default-agent-test",
            "broker_name": "Test Broker",
            "voice_id": "voice-abc",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["agent_name"] == "Jaumpablo"


async def test_create_client_duplicate_returns_409(clients_app_seeded: AsyncClient):
    """POST /clients with already existing client_id returns 409 Conflict."""
    response = await clients_app_seeded.post(
        "/api/v1/clients",
        json={
            "client_id": "quintana-seguros",
            "broker_name": "Quintana Seguros",
            "voice_id": "pNInz6obpgDQGcFmaJgB",
        },
    )
    assert response.status_code == 409


async def test_create_client_invalid_slug_uppercase_returns_422(
    clients_app: AsyncClient,
):
    """POST /clients with uppercase slug returns 422."""
    response = await clients_app.post(
        "/api/v1/clients",
        json={
            "client_id": "New-Broker",
            "broker_name": "New Broker",
            "voice_id": "abc",
        },
    )
    assert response.status_code == 422


async def test_create_client_invalid_slug_special_chars_returns_422(
    clients_app: AsyncClient,
):
    """POST /clients with special chars in slug returns 422."""
    response = await clients_app.post(
        "/api/v1/clients",
        json={
            "client_id": "new broker!",
            "broker_name": "New Broker",
            "voice_id": "abc",
        },
    )
    assert response.status_code == 422


async def test_create_client_invalid_slug_leading_hyphen_returns_422(
    clients_app: AsyncClient,
):
    """POST /clients with leading hyphen in slug returns 422."""
    response = await clients_app.post(
        "/api/v1/clients",
        json={
            "client_id": "-bad-slug",
            "broker_name": "Bad Slug",
            "voice_id": "abc",
        },
    )
    assert response.status_code == 422


async def test_create_client_invalid_slug_trailing_hyphen_returns_422(
    clients_app: AsyncClient,
):
    """POST /clients with trailing hyphen in slug returns 422."""
    response = await clients_app.post(
        "/api/v1/clients",
        json={
            "client_id": "bad-slug-",
            "broker_name": "Bad Slug",
            "voice_id": "abc",
        },
    )
    assert response.status_code == 422


async def test_create_client_is_retrievable(clients_app: AsyncClient):
    """Client created via POST is retrievable via GET."""
    await clients_app.post(
        "/api/v1/clients",
        json={
            "client_id": "test-retrievable",
            "broker_name": "Test Retrievable",
            "voice_id": "v123",
        },
    )
    response = await clients_app.get("/api/v1/clients/test-retrievable")
    assert response.status_code == 200
    assert response.json()["client_id"] == "test-retrievable"


# ---------------------------------------------------------------------------
# GET /api/v1/clients
# ---------------------------------------------------------------------------


async def test_list_clients_returns_empty_initially(clients_app: AsyncClient):
    """GET /clients returns empty list when no clients exist."""
    response = await clients_app.get("/api/v1/clients")
    assert response.status_code == 200
    assert response.json() == []


async def test_list_clients_returns_active_clients(clients_app: AsyncClient):
    """GET /clients returns all active clients."""
    # Create two clients
    for slug in ("broker-alpha", "broker-beta"):
        await clients_app.post(
            "/api/v1/clients",
            json={"client_id": slug, "broker_name": slug.title(), "voice_id": "v1"},
        )

    response = await clients_app.get("/api/v1/clients")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    slugs = {c["client_id"] for c in data}
    assert "broker-alpha" in slugs
    assert "broker-beta" in slugs


async def test_list_clients_excludes_soft_deleted(clients_app: AsyncClient):
    """GET /clients does NOT include soft-deleted clients."""
    # Create two clients
    for slug in ("keep-me", "delete-me"):
        await clients_app.post(
            "/api/v1/clients",
            json={"client_id": slug, "broker_name": slug.title(), "voice_id": "v1"},
        )

    # Soft-delete one
    await clients_app.delete("/api/v1/clients/delete-me")

    response = await clients_app.get("/api/v1/clients")
    assert response.status_code == 200
    data = response.json()
    slugs = [c["client_id"] for c in data]
    assert "keep-me" in slugs
    assert "delete-me" not in slugs


# ---------------------------------------------------------------------------
# GET /api/v1/clients/{client_id}
# ---------------------------------------------------------------------------


async def test_get_client_returns_200(clients_app_seeded: AsyncClient):
    """GET /clients/{id} returns 200 with client data."""
    response = await clients_app_seeded.get("/api/v1/clients/quintana-seguros")
    assert response.status_code == 200
    data = response.json()
    assert data["client_id"] == "quintana-seguros"
    assert data["broker_name"] == "Quintana Seguros"
    assert "is_active" in data
    assert "created_at" in data


async def test_get_client_not_found_returns_404(clients_app: AsyncClient):
    """GET /clients/{id} for unknown client returns 404."""
    response = await clients_app.get("/api/v1/clients/unknown-client")
    assert response.status_code == 404


async def test_get_client_response_shape(clients_app_seeded: AsyncClient):
    """GET /clients/{id} response has all expected fields."""
    response = await clients_app_seeded.get("/api/v1/clients/quintana-seguros")
    assert response.status_code == 200
    data = response.json()
    expected_fields = [
        "client_id",
        "broker_name",
        "agent_name",
        "voice_id",
        "is_active",
        "created_at",
    ]
    for field in expected_fields:
        assert field in data, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# PATCH /api/v1/clients/{client_id}
# ---------------------------------------------------------------------------


async def test_patch_client_updates_agent_name(clients_app_seeded: AsyncClient):
    """PATCH /clients/{id} with agent_name updates only that field."""
    response = await clients_app_seeded.patch(
        "/api/v1/clients/quintana-seguros",
        json={"agent_name": "JuanPablo"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["agent_name"] == "JuanPablo"
    # broker_name unchanged
    assert data["broker_name"] == "Quintana Seguros"


async def test_patch_client_updates_broker_name(clients_app_seeded: AsyncClient):
    """PATCH /clients/{id} with broker_name updates only that field."""
    response = await clients_app_seeded.patch(
        "/api/v1/clients/quintana-seguros",
        json={"broker_name": "Nueva Aseguradora"},
    )
    assert response.status_code == 200
    assert response.json()["broker_name"] == "Nueva Aseguradora"


async def test_patch_client_not_found_returns_404(clients_app: AsyncClient):
    """PATCH /clients/{id} for non-existent client returns 404."""
    response = await clients_app.patch(
        "/api/v1/clients/ghost-client",
        json={"agent_name": "Ghost"},
    )
    assert response.status_code == 404


async def test_patch_client_empty_body_returns_200(clients_app_seeded: AsyncClient):
    """PATCH /clients/{id} with empty body returns 200 (no-op update)."""
    response = await clients_app_seeded.patch(
        "/api/v1/clients/quintana-seguros",
        json={},
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# DELETE /api/v1/clients/{client_id}
# ---------------------------------------------------------------------------


async def test_delete_client_soft_deletes(clients_app: AsyncClient):
    """DELETE /clients/{id} sets is_active=False (soft delete)."""
    # Create a client first
    await clients_app.post(
        "/api/v1/clients",
        json={"client_id": "to-delete", "broker_name": "To Delete", "voice_id": "v1"},
    )

    response = await clients_app.delete("/api/v1/clients/to-delete")
    assert response.status_code == 200

    # Should not appear in active list
    list_resp = await clients_app.get("/api/v1/clients")
    slugs = [c["client_id"] for c in list_resp.json()]
    assert "to-delete" not in slugs


async def test_delete_client_not_found_returns_404(clients_app: AsyncClient):
    """DELETE /clients/{id} for non-existent client returns 404."""
    response = await clients_app.delete("/api/v1/clients/nonexistent-client")
    assert response.status_code == 404


async def test_delete_does_not_remove_db_record(clients_app: AsyncClient):
    """DELETE soft-deletes: record still exists in DB with is_active=False."""
    await clients_app.post(
        "/api/v1/clients",
        json={
            "client_id": "soft-delete-check",
            "broker_name": "Soft Delete Test",
            "voice_id": "v1",
        },
    )

    await clients_app.delete("/api/v1/clients/soft-delete-check")

    # Record still retrievable (GET returns the client even if inactive)
    # The router returns 200 for existing clients regardless of is_active
    from app.core import database as db_module
    from app.tenants.service import get_client

    async with db_module.async_session_factory() as session:
        client = await get_client(session, "soft-delete-check")
        assert client is not None
        assert client.is_active is False
