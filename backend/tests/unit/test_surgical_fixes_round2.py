"""Surgical fix tests — Round 2 (confirmed issues for feat/10-admin-crud).

Covers:
1. CRITICAL — PATCH tools_enabled: null → 422 (not 500)
2. WARNING — agent_count in ClientResponse and GET /api/v1/clients
3. WARNING — XSS: no raw string interpolation in onclick attributes
4. WARNING — Bootstrap slug sanitization for invalid agent_name chars
5. WARNING — Unexpected ValueError in deactivate/make-default → 500 (not 404)
6. WARNING — ClientCreate scheduler validators (timezone/hours/etc)
7. QUICK FIX — _require_client uses direct import (no __import__)
"""

from __future__ import annotations

from pathlib import Path

import pytest_asyncio
from pydantic import SecretStr
from httpx import AsyncClient, ASGITransport


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def agents_app(tmp_path: Path):
    """Isolated FastAPI app with agents router + a fresh SQLite DB.

    Pre-seeds one client ('test-client') with its default agent.
    """
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/agents_router_fix_test.db",
    )
    await db_module.init_db(settings)

    async with db_module.async_session_factory() as session:
        from app.tenants.service import create_client

        await create_client(
            session,
            id="test-client",
            name="Test Client SA",
            broker_name="Test Client SA",
            agent_name="Test Client Agent",
            voice_id="voice-default",
        )
        await session.commit()

    from app.agents.router import router as agents_router
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.include_router(agents_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
        follow_redirects=True,
    ) as client:
        yield client

    await db_module.close_db()


@pytest_asyncio.fixture
async def clients_app(tmp_path: Path):
    """Isolated FastAPI app with clients router + fresh SQLite DB."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/clients_router_fix_test.db",
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
async def db_session(tmp_path: Path):
    """Isolated async session for service-layer tests."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/fix_service_test.db",
    )
    await db_module.init_db(settings)
    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        yield sess
    await db_module.close_db()


# ---------------------------------------------------------------------------
# Fix 1 — PATCH tools_enabled: null → 422 (not 500)
# ---------------------------------------------------------------------------


async def test_patch_tools_enabled_null_returns_422(agents_app: AsyncClient):
    """PATCH with tools_enabled=null must return 422 (not 500 IntegrityError)."""
    # Get the default agent id
    list_resp = await agents_app.get("/api/v1/clients/test-client/agents")
    assert list_resp.status_code == 200
    agent_id = list_resp.json()[0]["agent_id"]

    resp = await agents_app.patch(
        f"/api/v1/clients/test-client/agents/{agent_id}",
        json={"tools_enabled": None},
    )
    assert resp.status_code == 422, (
        f"PATCH with tools_enabled=null must return 422, got {resp.status_code}. "
        "null tools_enabled should be rejected by Pydantic, not cause a DB IntegrityError."
    )


# Triangulation: valid tools_enabled list still works
async def test_patch_tools_enabled_valid_list_returns_200(agents_app: AsyncClient):
    """PATCH with valid tools_enabled list must return 200."""
    list_resp = await agents_app.get("/api/v1/clients/test-client/agents")
    assert list_resp.status_code == 200
    agent_id = list_resp.json()[0]["agent_id"]

    resp = await agents_app.patch(
        f"/api/v1/clients/test-client/agents/{agent_id}",
        json={"tools_enabled": ["get_lead_details"]},
    )
    assert resp.status_code == 200
    assert resp.json()["tools_enabled"] == ["get_lead_details"]


# ---------------------------------------------------------------------------
# Fix 2 — agent_count in ClientResponse
# ---------------------------------------------------------------------------


async def test_list_clients_includes_agent_count(clients_app: AsyncClient):
    """GET /api/v1/clients returns each client with agent_count >= 1 after create."""
    # Create a client — create_client bootstraps a default agent
    r = await clients_app.post(
        "/api/v1/clients",
        json={
            "client_id": "count-test-broker",
            "broker_name": "Count Test Broker SA",
            "voice_id": "v-count",
        },
    )
    assert r.status_code == 201

    resp = await clients_app.get("/api/v1/clients")
    assert resp.status_code == 200
    clients = resp.json()
    broker = next(c for c in clients if c["client_id"] == "count-test-broker")
    assert "agent_count" in broker, (
        "ClientResponse must include 'agent_count' field. Got: " + str(broker.keys())
    )
    assert broker["agent_count"] >= 1, (
        "agent_count must be >= 1 (create_client bootstraps a default agent). "
        f"Got: {broker['agent_count']}"
    )


# Triangulation: GET /api/v1/clients/{client_id} also includes agent_count
async def test_get_client_includes_agent_count(clients_app: AsyncClient):
    """GET /api/v1/clients/{id} returns client with agent_count."""
    r = await clients_app.post(
        "/api/v1/clients",
        json={
            "client_id": "count-get-broker",
            "broker_name": "Count Get Broker",
            "voice_id": "v-count-get",
        },
    )
    assert r.status_code == 201

    resp = await clients_app.get("/api/v1/clients/count-get-broker")
    assert resp.status_code == 200
    data = resp.json()
    assert "agent_count" in data
    assert data["agent_count"] >= 1


# ---------------------------------------------------------------------------
# Fix 3 — XSS: no raw string interpolation in onclick attributes
# ---------------------------------------------------------------------------


def test_admin_html_no_raw_interpolation_in_onclick():
    """admin.html must NOT use raw template literals inside onclick= attributes.

    The pattern onclick="someFunc('${...}'" is forbidden (XSS risk).
    Instead, data-* attributes or an escapeHtml() helper must be used.
    """
    import os
    import re

    backend_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    admin_path = os.path.join(backend_dir, "app", "static", "admin.html")
    with open(admin_path, encoding="utf-8") as f:
        html = f.read()

    # Look for onclick attributes that contain ${...} template literal interpolation
    # Pattern: onclick="...${...}..." inside HTML attributes
    raw_onclick_interpolation = re.findall(
        r'onclick=["\'][^"\']*\$\{[^}]+\}[^"\']*["\']', html
    )

    assert len(raw_onclick_interpolation) == 0, (
        f"admin.html has {len(raw_onclick_interpolation)} onclick attribute(s) with raw "
        f"template literal interpolation (XSS risk): {raw_onclick_interpolation[:3]!r}\n"
        "Fix: use an escapeHtml() helper or data-* attributes."
    )


# Triangulation: escapeHtml function must be present
def test_admin_html_has_escape_html_helper():
    """admin.html must define an escapeHtml() helper function."""
    import os

    backend_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    admin_path = os.path.join(backend_dir, "app", "static", "admin.html")
    with open(admin_path, encoding="utf-8") as f:
        html = f.read()

    assert "escapeHtml" in html, (
        "admin.html must define an escapeHtml() helper to prevent XSS. "
        "This function should be called on all user-controlled values before interpolation."
    )


# ---------------------------------------------------------------------------
# Fix 4 — Bootstrap slug sanitization
# ---------------------------------------------------------------------------


async def test_bootstrap_agent_name_with_special_chars_produces_valid_slug(
    db_session,
):
    """create_client with agent_name='My Agent (2.0)!' must produce a valid slug.

    The bootstrapped agent's slug must match ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$.
    Invalid chars must be stripped, not stored.
    """
    import re
    from app.tenants.service import create_client, get_default_agent

    _SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")

    await create_client(
        db_session,
        id="special-chars-client",
        name="Special Chars Client",
        broker_name="Special Chars SA",
        agent_name="My Agent (2.0)!",
        voice_id="v-special",
    )
    await db_session.flush()

    agent = await get_default_agent(db_session, "special-chars-client")
    assert agent is not None
    assert _SLUG_RE.match(agent.slug) is not None, (
        f"Bootstrapped agent slug {agent.slug!r} does not match "
        f"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$. "
        "create_client must sanitize agent_name before using it as slug."
    )


# Triangulation: simple names still produce correct slugs
async def test_bootstrap_simple_agent_name_produces_correct_slug(db_session):
    """create_client with agent_name='Jaumpablo' produces slug 'jaumpablo'."""
    from app.tenants.service import create_client, get_default_agent

    await create_client(
        db_session,
        id="simple-slug-client",
        name="Simple Slug Client",
        broker_name="Simple SA",
        agent_name="Jaumpablo",
        voice_id="v-simple",
    )
    await db_session.flush()

    agent = await get_default_agent(db_session, "simple-slug-client")
    assert agent is not None
    assert agent.slug == "jaumpablo"


# ---------------------------------------------------------------------------
# Fix 5 — Unexpected ValueError does NOT map to 404
# ---------------------------------------------------------------------------


async def test_unexpected_value_error_in_service_returns_500_not_404(
    agents_app: AsyncClient,
    monkeypatch,
):
    """Unexpected ValueError from service must return 500, not 404.

    The router currently catches ALL ValueErrors and returns 404, which is
    misleading when the error is unrelated to 'not found'.
    """
    import app.tenants.service as svc

    async def _bad_deactivate(*args, **kwargs):
        raise ValueError("completely_unexpected_error: something went wrong internally")

    monkeypatch.setattr(svc, "deactivate_agent", _bad_deactivate)

    list_resp = await agents_app.get("/api/v1/clients/test-client/agents")
    agent_id = list_resp.json()[0]["agent_id"]

    resp = await agents_app.post(
        f"/api/v1/clients/test-client/agents/{agent_id}/deactivate"
    )
    # Must NOT return 404 for an unexpected ValueError
    assert resp.status_code != 404, (
        "Unexpected ValueError must NOT map to 404 'agent not found'. "
        f"Got {resp.status_code}. The router must distinguish known sentinel errors "
        "from unexpected internal errors."
    )


# Triangulation: known sentinel ValueError still returns 409
async def test_known_sentinel_value_error_still_returns_409(
    agents_app: AsyncClient,
):
    """POST /deactivate on the sole default agent still returns 409 (sentinel check)."""
    list_resp = await agents_app.get("/api/v1/clients/test-client/agents")
    agents = list_resp.json()
    default_agent = next(a for a in agents if a["is_default"])
    agent_id = default_agent["agent_id"]

    resp = await agents_app.post(
        f"/api/v1/clients/test-client/agents/{agent_id}/deactivate"
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Fix 6 — ClientCreate scheduler validators
# ---------------------------------------------------------------------------


async def test_create_client_invalid_timezone_returns_422(clients_app: AsyncClient):
    """POST /api/v1/clients with scheduler_timezone='Invalid/Zone' → 422."""
    resp = await clients_app.post(
        "/api/v1/clients",
        json={
            "client_id": "tz-invalid-test",
            "broker_name": "TZ Invalid",
            "voice_id": "v-tz",
            "scheduler_timezone": "Invalid/Zone",
        },
    )
    assert resp.status_code == 422, (
        f"ClientCreate must validate scheduler_timezone. Got {resp.status_code}. "
        "Invalid IANA timezone strings must be rejected."
    )


# Triangulation: valid timezone passes
async def test_create_client_valid_timezone_returns_201(clients_app: AsyncClient):
    """POST /api/v1/clients with valid timezone → 201."""
    resp = await clients_app.post(
        "/api/v1/clients",
        json={
            "client_id": "tz-valid-test",
            "broker_name": "TZ Valid",
            "voice_id": "v-tz-valid",
            "scheduler_timezone": "Europe/Madrid",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["scheduler_timezone"] == "Europe/Madrid"


async def test_create_client_invalid_max_attempts_returns_422(clients_app: AsyncClient):
    """POST /api/v1/clients with scheduler_max_attempts=0 → 422."""
    resp = await clients_app.post(
        "/api/v1/clients",
        json={
            "client_id": "attempts-invalid",
            "broker_name": "Attempts Invalid",
            "voice_id": "v1",
            "scheduler_max_attempts": 0,
        },
    )
    assert resp.status_code == 422, (
        f"ClientCreate must validate scheduler_max_attempts >= 1. Got {resp.status_code}."
    )


async def test_create_client_invalid_cooldown_returns_422(clients_app: AsyncClient):
    """POST /api/v1/clients with scheduler_cooldown_minutes=-1 → 422."""
    resp = await clients_app.post(
        "/api/v1/clients",
        json={
            "client_id": "cooldown-invalid",
            "broker_name": "Cooldown Invalid",
            "voice_id": "v1",
            "scheduler_cooldown_minutes": -1,
        },
    )
    assert resp.status_code == 422, (
        f"ClientCreate must validate scheduler_cooldown_minutes >= 0. Got {resp.status_code}."
    )


async def test_create_client_invalid_hour_range_returns_422(clients_app: AsyncClient):
    """POST /api/v1/clients with hours_start=25 → 422."""
    resp = await clients_app.post(
        "/api/v1/clients",
        json={
            "client_id": "hour-invalid",
            "broker_name": "Hour Invalid",
            "voice_id": "v1",
            "scheduler_allowed_hours_start": 25,
        },
    )
    assert resp.status_code == 422, (
        f"ClientCreate must validate hour values in [0, 23]. Got {resp.status_code}."
    )


async def test_create_client_invalid_retry_outcomes_returns_422(
    clients_app: AsyncClient,
):
    """POST /api/v1/clients with scheduler_retry_on_outcomes='not-json' → 422."""
    resp = await clients_app.post(
        "/api/v1/clients",
        json={
            "client_id": "retry-invalid",
            "broker_name": "Retry Invalid",
            "voice_id": "v1",
            "scheduler_retry_on_outcomes": "not-json",
        },
    )
    assert resp.status_code == 422, (
        f"ClientCreate must validate scheduler_retry_on_outcomes is valid JSON array. "
        f"Got {resp.status_code}."
    )


# ---------------------------------------------------------------------------
# Fix 7 — _require_client uses direct import (no __import__)
# ---------------------------------------------------------------------------


def test_require_client_uses_direct_import():
    """_require_client must import Client directly, not via __import__."""
    import inspect
    from app.agents import router as agents_router_module

    source = inspect.getsource(agents_router_module)
    assert "__import__" not in source, (
        "agents/router.py must not use __import__(). "
        "Use 'from app.tenants.models import Client' directly."
    )
