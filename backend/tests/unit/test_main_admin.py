"""Tests for agents router registration and admin UI via the full app.

Verifies:
- GET /api/v1/clients/{client_id}/agents is accessible via the full app
- GET /admin returns 200 HTML containing generic "Company Name" label
- GET /admin HTML does NOT contain a client_id input field for creation
"""

from __future__ import annotations

from pathlib import Path

import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


@pytest_asyncio.fixture
async def full_app(tmp_path: Path):
    """Minimal full app fixture that wires agents router.

    We do NOT use the real lifespan to avoid seeding / external deps.
    Instead we initialise DB manually so we get agents endpoint.
    """
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/main_admin_test.db",
    )
    await db_module.init_db(settings)

    # Seed one client so we can test the agents endpoint through the full router
    async with db_module.async_session_factory() as session:
        from app.tenants.service import create_client

        await create_client(
            session,
            id="admin-test-client",
            name="Admin Test Client",
            broker_name="Admin Test Client",
            agent_name="AdminAgent",
            voice_id="voice-admin",
        )
        await session.commit()

    # Build a mini app that mimics main.py router registration
    from fastapi import FastAPI, APIRouter
    from app.clients.router import router as clients_router
    from app.agents.router import router as agents_router

    mini_app = FastAPI()
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(clients_router)
    api_v1.include_router(agents_router)
    mini_app.include_router(api_v1)

    async with AsyncClient(
        transport=ASGITransport(app=mini_app),
        base_url="http://test",
        follow_redirects=True,
    ) as client:
        yield client

    await db_module.close_db()


async def test_agents_endpoint_accessible_via_full_app(full_app: AsyncClient):
    """GET /api/v1/clients/{client_id}/agents is routed correctly in full app."""
    response = await full_app.get("/api/v1/clients/admin-test-client/agents")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1  # default agent auto-created
    assert data[0]["client_id"] == "admin-test-client"


# ---------------------------------------------------------------------------
# Admin UI tests (task 3.1) — GET /admin
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def admin_app(tmp_path: Path):
    """Full app fixture that mounts the /admin static UI.

    Builds the same structure as main.py (StaticFiles at /admin) so we can
    hit GET /admin and assert the HTML content.
    """
    import os

    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/admin_ui_test.db",
    )
    await db_module.init_db(settings)

    from fastapi import FastAPI
    from starlette.staticfiles import StaticFiles

    mini_app = FastAPI()

    # admin subdirectory — same pattern as main.py (/demo → static/, /admin → static/admin/)
    admin_dir = os.path.join(
        os.path.dirname(__file__), "..", "..", "app", "static", "admin"
    )
    admin_dir = os.path.normpath(admin_dir)

    # Mount /admin — same pattern as main.py
    mini_app.mount("/admin", StaticFiles(directory=admin_dir, html=True), name="admin")

    async with AsyncClient(
        transport=ASGITransport(app=mini_app),
        base_url="http://test",
        follow_redirects=True,
    ) as client:
        yield client

    await db_module.close_db()


async def test_admin_returns_200_html(admin_app: AsyncClient):
    """GET /admin returns 200 with HTML content-type."""
    response = await admin_app.get("/admin")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")


async def test_admin_html_contains_company_name_label(admin_app: AsyncClient):
    """GET /admin HTML contains generic 'Company Name' label, not 'Broker Name'."""
    response = await admin_app.get("/admin")
    html = response.text
    # Must use generic label
    assert "Company Name" in html
    # Must NOT use broker-specific label
    assert "Broker Name" not in html


async def test_admin_html_has_no_client_id_creation_input(admin_app: AsyncClient):
    """GET /admin create-client form does NOT contain a client_id input field.

    Triangulation of test_admin_html_contains_company_name_label:
    Different assertion — verifies the hidden-field design decision (no exposed
    client_id input so the admin calls POST /clients without client_id).
    """
    response = await admin_app.get("/admin")
    html = response.text
    # The create-client form must NOT expose a client_id text input
    assert 'id="newClientId"' not in html
    assert 'name="client_id"' not in html
