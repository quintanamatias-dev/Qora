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
            "name": "New Broker SA",
            "agent_name": "Ana",
            "voice_id": "abc123",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["client_id"] == "new-broker"
    assert data["name"] == "New Broker SA"
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
            "name": "Test Broker",
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
            "name": "Quintana Seguros",
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
            "name": "New Broker",
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
            "name": "New Broker",
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
            "name": "Bad Slug",
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
            "name": "Bad Slug",
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
            "name": "Test Retrievable",
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
            json={"client_id": slug, "name": slug.title(), "voice_id": "v1"},
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
            json={"client_id": slug, "name": slug.title(), "voice_id": "v1"},
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
    assert data["name"] == "Quintana Seguros"
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
        "name",
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
    # name unchanged
    assert data["name"] == "Quintana Seguros"


async def test_patch_client_updates_name(clients_app_seeded: AsyncClient):
    """PATCH /clients/{id} with name updates only that field."""
    response = await clients_app_seeded.patch(
        "/api/v1/clients/quintana-seguros",
        json={"name": "Nueva Aseguradora"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Nueva Aseguradora"


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
        json={"client_id": "to-delete", "name": "To Delete", "voice_id": "v1"},
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


# ---------------------------------------------------------------------------
# Round 2 fix: partial PATCH hour validation
# Issue 2 — Partial PATCH bypasses hour validation
# ---------------------------------------------------------------------------


async def test_patch_client_partial_hours_start_greater_than_stored_end_returns_422(
    clients_app_seeded: AsyncClient,
):
    """PATCH with only start_hour that exceeds stored end_hour must return 422.

    Current stored values: start=9, end=20.
    Sending start=22 alone should fail because 22 >= 20 (stored end).
    """
    response = await clients_app_seeded.patch(
        "/api/v1/clients/quintana-seguros",
        json={"scheduler_allowed_hours_start": 22},
    )
    assert (
        response.status_code == 422
    ), f"Expected 422 when partial PATCH sets start=22 > stored end=20, got {response.status_code}"


async def test_patch_client_partial_hours_end_less_than_stored_start_returns_422(
    clients_app_seeded: AsyncClient,
):
    """PATCH with only end_hour less than stored start_hour must return 422.

    Current stored values: start=9, end=20.
    Sending end=5 alone should fail because 9 (stored start) >= 5.
    """
    response = await clients_app_seeded.patch(
        "/api/v1/clients/quintana-seguros",
        json={"scheduler_allowed_hours_end": 5},
    )
    assert (
        response.status_code == 422
    ), f"Expected 422 when partial PATCH sets end=5 < stored start=9, got {response.status_code}"


async def test_patch_client_valid_hours_update_succeeds(
    clients_app_seeded: AsyncClient,
):
    """PATCH with valid combined hours (start < end) must succeed."""
    response = await clients_app_seeded.patch(
        "/api/v1/clients/quintana-seguros",
        json={"scheduler_allowed_hours_start": 8, "scheduler_allowed_hours_end": 18},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["scheduler_allowed_hours_start"] == 8
    assert data["scheduler_allowed_hours_end"] == 18


async def test_patch_client_hours_equal_returns_422(clients_app_seeded: AsyncClient):
    """PATCH with start == end must return 422 (start must be strictly less than end)."""
    response = await clients_app_seeded.patch(
        "/api/v1/clients/quintana-seguros",
        json={"scheduler_allowed_hours_start": 10, "scheduler_allowed_hours_end": 10},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Phase 6 — Scheduler config fields in client responses
# ---------------------------------------------------------------------------


async def test_create_client_response_includes_scheduler_fields(
    clients_app: AsyncClient,
):
    """POST /clients response includes scheduler config fields with defaults."""
    response = await clients_app.post(
        "/api/v1/clients",
        json={
            "client_id": "sched-broker",
            "name": "Sched Broker SA",
            "voice_id": "v1",
        },
    )
    assert response.status_code == 201
    data = response.json()
    # Scheduler fields with default values
    assert data["scheduler_enabled"] is False
    assert data["scheduler_max_attempts"] == 3
    assert data["scheduler_cooldown_minutes"] == 60
    assert data["scheduler_allowed_hours_start"] == 9
    assert data["scheduler_allowed_hours_end"] == 20
    assert "scheduler_retry_on_outcomes" in data
    assert data["scheduler_timezone"] == "America/Argentina/Buenos_Aires"


async def test_patch_client_enables_scheduler(clients_app_seeded: AsyncClient):
    """PATCH /clients/{id} with scheduler_enabled=True persists the change."""
    response = await clients_app_seeded.patch(
        "/api/v1/clients/quintana-seguros",
        json={"scheduler_enabled": True},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["scheduler_enabled"] is True


async def test_patch_client_scheduler_cooldown(clients_app_seeded: AsyncClient):
    """PATCH /clients/{id} updates scheduler_cooldown_minutes."""
    response = await clients_app_seeded.patch(
        "/api/v1/clients/quintana-seguros",
        json={"scheduler_cooldown_minutes": 120},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["scheduler_cooldown_minutes"] == 120


async def test_delete_does_not_remove_db_record(clients_app: AsyncClient):
    """DELETE soft-deletes: record still exists in DB with is_active=False."""
    await clients_app.post(
        "/api/v1/clients",
        json={
            "client_id": "soft-delete-check",
            "name": "Soft Delete Test",
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


# ---------------------------------------------------------------------------
# Phase 7 — Task 1.2: Client POST must bootstrap default Agent via service
# ---------------------------------------------------------------------------


async def test_create_client_bootstraps_default_agent(clients_app: AsyncClient):
    """POST /clients creates a default Agent row via service.create_client().

    This verifies the regression fix: the router MUST call service.create_client()
    rather than constructing Client() directly, so Agent bootstrap happens.
    """
    response = await clients_app.post(
        "/api/v1/clients",
        json={
            "client_id": "agent-bootstrap-test",
            "name": "Bootstrap Test",
            "voice_id": "v-bootstrap",
        },
    )
    assert response.status_code == 201

    # Verify that a default Agent row was created in DB
    from app.core import database as db_module
    from app.tenants.service import get_default_agent

    async with db_module.async_session_factory() as session:
        default_agent = await get_default_agent(session, "agent-bootstrap-test")
        assert default_agent is not None, (
            "POST /clients must bootstrap a default Agent via service.create_client(). "
            "The current router constructs Client() directly, bypassing Agent bootstrap."
        )
        assert default_agent.is_default is True
        assert default_agent.is_active is True
        assert default_agent.client_id == "agent-bootstrap-test"


async def test_create_client_duplicate_via_service_returns_409(
    clients_app_seeded: AsyncClient,
):
    """POST /clients with duplicate client_id returns 409 (regression: via service)."""
    response = await clients_app_seeded.post(
        "/api/v1/clients",
        json={
            "client_id": "quintana-seguros",
            "name": "Quintana Seguros Dup",
            "voice_id": "v1",
        },
    )
    assert response.status_code == 409
    data = response.json()
    assert data["detail"]["error"] == "client already exists"
    assert data["detail"]["client_id"] == "quintana-seguros"


# ---------------------------------------------------------------------------
# Phase 7 — Task 1.3: ClientCreate with scheduler fields
# ---------------------------------------------------------------------------


async def test_create_client_with_custom_scheduler_fields(clients_app: AsyncClient):
    """POST /clients with scheduler fields persists custom scheduler config.

    ClientCreate must accept scheduler fields so clients can be bootstrapped
    with non-default scheduler settings in a single request.
    """
    response = await clients_app.post(
        "/api/v1/clients",
        json={
            "client_id": "sched-custom",
            "name": "Sched Custom",
            "voice_id": "v1",
            "scheduler_enabled": True,
            "scheduler_max_attempts": 5,
            "scheduler_cooldown_minutes": 30,
            "scheduler_allowed_hours_start": 8,
            "scheduler_allowed_hours_end": 18,
            "scheduler_timezone": "Europe/Madrid",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["scheduler_enabled"] is True
    assert data["scheduler_max_attempts"] == 5
    assert data["scheduler_cooldown_minutes"] == 30
    assert data["scheduler_allowed_hours_start"] == 8
    assert data["scheduler_allowed_hours_end"] == 18
    assert data["scheduler_timezone"] == "Europe/Madrid"


async def test_create_client_scheduler_defaults_when_omitted(clients_app: AsyncClient):
    """POST /clients without scheduler fields uses defaults."""
    response = await clients_app.post(
        "/api/v1/clients",
        json={
            "client_id": "sched-defaults",
            "name": "Sched Defaults",
            "voice_id": "v1",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["scheduler_enabled"] is False
    assert data["scheduler_max_attempts"] == 3
    assert data["scheduler_timezone"] == "America/Argentina/Buenos_Aires"


# ---------------------------------------------------------------------------
# qora-demo-agent-admin-fix — Task 1.1 + 1.2: Optional client_id + collision dedup
# ---------------------------------------------------------------------------


async def test_create_client_without_client_id_auto_generates_slug(
    clients_app: AsyncClient,
):
    """POST /clients without client_id auto-generates slug from name.

    'Qora Demo' → 'qora-demo'
    """
    response = await clients_app.post(
        "/api/v1/clients",
        json={"name": "Qora Demo"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["client_id"] == "qora-demo"
    assert data["name"] == "Qora Demo"
    assert data["is_active"] is True


async def test_create_client_explicit_client_id_backward_compatible(
    clients_app: AsyncClient,
):
    """POST /clients with explicit client_id still uses that value (backward compat)."""
    response = await clients_app.post(
        "/api/v1/clients",
        json={"name": "Acme Corp", "client_id": "my-custom-id"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["client_id"] == "my-custom-id"


async def test_create_client_slug_collision_appends_suffix(
    clients_app: AsyncClient,
):
    """POST /clients with slug collision yields slug with -2 suffix.

    First 'Qora Demo' → 'qora-demo'. Second distinct name slugifies to 'qora-demo-2'.
    """
    # First: creates qora-demo
    r1 = await clients_app.post(
        "/api/v1/clients",
        json={"name": "Qora Demo"},
    )
    assert r1.status_code == 201
    assert r1.json()["client_id"] == "qora-demo"

    # Second: generated slug collides, but name stays unique.
    r2 = await clients_app.post(
        "/api/v1/clients",
        json={"name": "Qora-Demo"},
    )
    assert r2.status_code == 201
    assert r2.json()["client_id"] == "qora-demo-2"


async def test_create_client_multiple_collisions_increment_suffix(
    clients_app: AsyncClient,
):
    """POST /clients with double collision yields -3 suffix.

    Existing slugs qora-demo and qora-demo-2 → third request yields qora-demo-3.
    """
    await clients_app.post("/api/v1/clients", json={"name": "Qora Demo"})
    await clients_app.post("/api/v1/clients", json={"name": "Qora-Demo"})

    r3 = await clients_app.post(
        "/api/v1/clients",
        json={"name": "Qora_Demo"},
    )
    assert r3.status_code == 201
    assert r3.json()["client_id"] == "qora-demo-3"


async def test_create_client_name_with_special_chars_slugified(
    clients_app: AsyncClient,
):
    """POST /clients with special chars in name generates ASCII-only slug.

    'Acme Corp!' → 'acme-corp'
    Triangulation: different input → different but valid slug (not empty, no special chars).
    """
    response = await clients_app.post(
        "/api/v1/clients",
        json={"name": "Acme Corp!"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["client_id"] == "acme-corp"
    # name preserved as-is in response
    assert data["name"] == "Acme Corp!"
