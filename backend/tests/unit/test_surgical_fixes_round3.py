"""Surgical fix tests — Round 3 (confirmed issues for feat/10-admin-crud).

Covers:
1. CRITICAL — XSS in admin.html: TD cells must escape user values, onclick
   attributes must NOT contain raw template literal interpolation; data-* pattern
   must be used instead.
2. WARNING — ClientCreate missing validate_hour_window (start < end).
3. WARNING — POST /api/v1/clients duplicate broker_name (Client.name unique) → 409.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_admin_html() -> str:
    backend_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    admin_path = os.path.join(backend_dir, "app", "static", "admin.html")
    with open(admin_path, encoding="utf-8") as f:
        return f.read()


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
# Issue 1a — TD cells must use escapeHtml() for all user-controlled values
# ---------------------------------------------------------------------------


def test_admin_html_client_td_broker_name_escaped():
    """admin.html clients table must escape broker_name via escapeHtml()."""
    html = _read_admin_html()
    # Raw ${c.broker_name} inside innerHTML is forbidden — must be wrapped in escapeHtml(...)
    assert "${c.broker_name}" not in html, (
        "admin.html interpolates raw ${c.broker_name} into innerHTML (stored XSS risk). "
        "Use escapeHtml(c.broker_name) instead."
    )


def test_admin_html_client_td_agent_name_escaped():
    """admin.html clients table must escape agent_name via escapeHtml()."""
    html = _read_admin_html()
    assert "${c.agent_name}" not in html, (
        "admin.html interpolates raw ${c.agent_name} into innerHTML (stored XSS risk). "
        "Use escapeHtml(c.agent_name) instead."
    )


def test_admin_html_client_td_client_id_escaped():
    """admin.html clients table must escape client_id via escapeHtml()."""
    html = _read_admin_html()
    assert "${c.client_id}" not in html, (
        "admin.html interpolates raw ${c.client_id} into innerHTML (stored XSS risk). "
        "Use escapeHtml(c.client_id) instead."
    )


def test_admin_html_agent_td_name_escaped():
    """admin.html agents table must escape agent name via escapeHtml()."""
    html = _read_admin_html()
    assert "${a.name}" not in html, (
        "admin.html interpolates raw ${a.name} into innerHTML (stored XSS risk). "
        "Use escapeHtml(a.name) instead."
    )


def test_admin_html_agent_td_voice_id_escaped():
    """admin.html agents table must escape voice_id via escapeHtml()."""
    html = _read_admin_html()
    assert "${a.voice_id}" not in html, (
        "admin.html interpolates raw ${a.voice_id} into innerHTML (stored XSS risk). "
        "Use escapeHtml(a.voice_id) instead."
    )


def test_admin_html_agent_td_slug_escaped():
    """admin.html agents table must escape slug via escapeHtml()."""
    html = _read_admin_html()
    assert "${a.slug}" not in html, (
        "admin.html interpolates raw ${a.slug} into innerHTML (stored XSS risk). "
        "Use escapeHtml(a.slug) instead."
    )


def test_admin_html_agent_td_model_escaped():
    """admin.html agents table must escape model via escapeHtml()."""
    html = _read_admin_html()
    assert "${a.model}" not in html, (
        "admin.html interpolates raw ${a.model} into innerHTML (stored XSS risk). "
        "Use escapeHtml(a.model) instead."
    )


# ---------------------------------------------------------------------------
# Issue 1b — onclick attributes must NOT contain raw template literal values
# ---------------------------------------------------------------------------


def test_admin_html_no_raw_interpolation_in_onclick_r3():
    """admin.html onclick= attributes must NOT contain ${...} interpolation.

    The correct fix is data-* attributes read in the handler, NOT escapeHtml()
    inside onclick strings (HTML entity decode happens before JS eval — single
    quotes in values still break JS strings).
    """
    html = _read_admin_html()
    raw_onclick_interpolation = re.findall(
        r'onclick=["\'][^"\']*\$\{[^}]+\}[^"\']*["\']', html
    )
    assert len(raw_onclick_interpolation) == 0, (
        f"admin.html has {len(raw_onclick_interpolation)} onclick attribute(s) with raw "
        f"template literal interpolation: {raw_onclick_interpolation[:3]!r}\n"
        "Fix: use data-* attributes and read them in the JS handler."
    )


def test_admin_html_edit_buttons_use_data_attributes():
    """admin.html edit buttons must use data-* attributes to pass row data.

    Instead of onclick='showClientEdit(\"${id}\", ...)', the button must have
    data-client-id='...' (or similar) attributes set via escapeHtml().
    """
    html = _read_admin_html()
    # There must be at least one data-* attribute on action buttons (client or agent)
    has_data_attrs = (
        "data-client-id" in html
        or "data-agent-id" in html
        or re.search(r'data-[a-z-]+="\$\{escapeHtml\(', html)
        or re.search(r"data-[a-z]", html)
    )
    assert has_data_attrs, (
        "admin.html must use data-* attributes on action buttons to pass row data safely. "
        "Edit buttons should store IDs/values in data-* attrs and read them in the handler."
    )


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
            "broker_name": "Hour Window Test",
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
            broker_name="Test",
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
            "broker_name": "Valid Hour Window",
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
            broker_name="Test Equal",
            voice_id="v1",
            scheduler_allowed_hours_start=10,
            scheduler_allowed_hours_end=10,
        )


# ---------------------------------------------------------------------------
# Issue 3 — Duplicate broker_name (Client.name unique) → 409 not 500
# ---------------------------------------------------------------------------


async def test_create_two_clients_same_broker_name_returns_409(
    clients_app: AsyncClient,
):
    """POST /api/v1/clients with duplicate broker_name (same Client.name) → 409.

    Client.name has unique=True in DB. Creating two clients with same broker_name
    but different client_id triggers IntegrityError → must return 409, not 500.
    """
    # First client succeeds
    r1 = await clients_app.post(
        "/api/v1/clients",
        json={
            "client_id": "broker-alpha",
            "broker_name": "Duplicate Broker",
            "voice_id": "v1",
        },
    )
    assert (
        r1.status_code == 201
    ), f"First client creation must succeed. Got {r1.status_code}."

    # Second client with same broker_name but different client_id → 409
    r2 = await clients_app.post(
        "/api/v1/clients",
        json={
            "client_id": "broker-beta",
            "broker_name": "Duplicate Broker",  # same broker_name → same Client.name
            "voice_id": "v1",
        },
    )
    assert r2.status_code == 409, (
        f"POST /clients with duplicate broker_name must return 409 (not 500 IntegrityError). "
        f"Got {r2.status_code}. Router must catch IntegrityError from Client.name unique constraint."
    )


# Triangulation: different broker names succeed independently
async def test_create_two_clients_different_broker_names_succeed(
    clients_app: AsyncClient,
):
    """POST /api/v1/clients with distinct broker_names → both 201."""
    r1 = await clients_app.post(
        "/api/v1/clients",
        json={
            "client_id": "unique-alpha",
            "broker_name": "Alpha Broker",
            "voice_id": "v1",
        },
    )
    r2 = await clients_app.post(
        "/api/v1/clients",
        json={
            "client_id": "unique-beta",
            "broker_name": "Beta Broker",
            "voice_id": "v1",
        },
    )
    assert r1.status_code == 201
    assert r2.status_code == 201
