"""Tests for agents router registration and admin UI routing.

Verifies:
- GET /api/v1/clients/{client_id}/agents is accessible via the full app
- GET /admin and GET /admin/ redirect (307) to http://localhost:5173/admin (canonical admin)
- The backend does NOT serve a duplicate static admin UI
- The canonical admin UI is the React/Vite frontend at http://localhost:5173/admin

NOTE: The backend static admin (backend/app/static/admin/index.html) has been
removed. The single admin source of truth is the React/Vite frontend. HTML-content
tests have been moved to frontend/src/features/admin/*.test.tsx.
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
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations
    await _init_db_with_migrations(db_module, settings)

    # Seed one client so we can test the agents endpoint through the full router
    async with db_module.async_session_factory() as session:
        from app.tenants.service import create_client

        await create_client(
            session,
            id="admin-test-client",
            name="Admin Test Client",
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
# Single admin source of truth — backend /admin must redirect to React frontend
# ---------------------------------------------------------------------------


async def test_main_app_redirects_admin_slash(tmp_path: Path):
    """The real main.py app must redirect /admin/ to the canonical frontend admin.

    The admin UI is the React/Vite frontend at http://localhost:5173/admin.
    The backend must NOT serve a duplicate static admin (that would create two
    sources of truth), but it MUST redirect browsers to the canonical URL so
    hitting the backend /admin URL does not return 404.

    GET /admin/ → 307 redirect to http://localhost:5173/admin
    """
    from app.main import app as main_app

    async with AsyncClient(
        transport=ASGITransport(app=main_app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        response = await client.get("/admin/")
        # Must redirect — not 200 (duplicate UI) and not 404 (bad UX)
        assert response.status_code == 307, (
            f"Expected 307 redirect from /admin/ but got {response.status_code}. "
            "Backend /admin must redirect to the canonical React/Vite frontend admin."
        )
        assert response.headers["location"] == "http://localhost:5173/admin", (
            f"Redirect location mismatch: {response.headers.get('location')}. "
            "Must point to http://localhost:5173/admin (no trailing slash)."
        )


async def test_main_app_redirects_admin_no_slash(tmp_path: Path):
    """GET /admin (no trailing slash) must also redirect to the canonical frontend admin.

    Both /admin and /admin/ must redirect — users/browsers may omit the slash.
    """
    from app.main import app as main_app

    async with AsyncClient(
        transport=ASGITransport(app=main_app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        response = await client.get("/admin")
        assert response.status_code == 307, (
            f"Expected 307 redirect from /admin but got {response.status_code}. "
            "Both /admin and /admin/ must redirect to the canonical frontend admin."
        )
        assert response.headers["location"] == "http://localhost:5173/admin", (
            f"Redirect location mismatch: {response.headers.get('location')}."
        )


# ---------------------------------------------------------------------------
# Backend does NOT serve static admin HTML
# ---------------------------------------------------------------------------


def test_static_admin_html_file_deleted():
    """The static admin HTML file must be deleted (single source of truth is React).

    This test ensures no one accidentally re-adds the old static admin.
    The canonical admin UI is the React/Vite frontend at http://localhost:5173/admin.
    HTML-content assertions (TTS fields, form labels) live in
    frontend/src/features/admin/agents-panel.test.tsx.
    """
    admin_html = (
        Path(__file__).parent.parent.parent / "app" / "static" / "admin" / "index.html"
    )
    assert not admin_html.exists(), (
        f"Static admin HTML found at {admin_html}. "
        "This file must be deleted — the single admin source of truth is "
        "the React/Vite frontend at http://localhost:5173/admin. "
        "Do NOT re-add a backend static admin UI."
    )
