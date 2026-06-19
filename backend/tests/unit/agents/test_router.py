"""Unit/integration tests for the agents CRUD router.

Tests cover Phase 3:
  Task 3.1:
  - GET  /api/v1/clients/{client_id}/agents — list agents for client
  - POST /api/v1/clients/{client_id}/agents — create agent (201)
  - GET  /api/v1/clients/{client_id}/agents/{agent_id} — single agent
  - 404 when client not found
  - 404 when agent not found
  - 409 on slug duplicate
  - 422 on invalid tools

  Task 3.2:
  - PATCH /{agent_id} — partial update
  - POST  /{agent_id}/deactivate — soft delete
  - POST  /{agent_id}/make-default — atomic default swap
  - 404 / 409 guard errors on each
"""

from __future__ import annotations

from pathlib import Path

import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Shared test payload helpers
# ---------------------------------------------------------------------------

_VALID_AGENT = {
    "slug": "test-agent",
    "name": "Test Agent",
    "voice_id": "voice-abc123",
}

_VALID_AGENT_2 = {
    "slug": "second-agent",
    "name": "Second Agent",
    "voice_id": "voice-xyz789",
}

_BASE = "/api/v1/clients/test-client/agents"
_BASE_EMPTY = "/api/v1/clients/nonexistent/agents"


# ---------------------------------------------------------------------------
# Fixtures
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
        database_url=f"sqlite+aiosqlite:///{tmp_path}/agents_router_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations
    await _init_db_with_migrations(db_module, settings)

    # Seed a test client (auto-creates default agent with slug 'test-client-agent')
    async with db_module.async_session_factory() as session:
        from app.tenants.service import create_client

        await create_client(
            session,
            id="test-client",
            name="Test Client SA",
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
async def agents_app_empty(tmp_path: Path):
    """Isolated FastAPI app with NO clients seeded (for 404 tests)."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/agents_empty_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations
    await _init_db_with_migrations(db_module, settings)

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


# ---------------------------------------------------------------------------
# Task 3.1: GET list — /api/v1/clients/{client_id}/agents
# ---------------------------------------------------------------------------


async def test_list_agents_returns_200_with_default_agent(agents_app: AsyncClient):
    """GET /clients/test-client/agents returns 200 with the seeded default agent."""
    response = await agents_app.get(_BASE)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    agent = data[0]
    assert agent["client_id"] == "test-client"
    assert agent["is_default"] is True
    assert agent["is_active"] is True
    assert "agent_id" in agent
    assert "slug" in agent


async def test_list_agents_client_not_found_returns_404(
    agents_app_empty: AsyncClient,
):
    """GET /clients/nonexistent/agents returns 404 when client doesn't exist."""
    response = await agents_app_empty.get(_BASE_EMPTY)
    assert response.status_code == 404
    data = response.json()
    assert data["detail"]["error"] == "client not found"


# ---------------------------------------------------------------------------
# Task 3.1: POST create — /api/v1/clients/{client_id}/agents
# ---------------------------------------------------------------------------


async def test_create_agent_returns_201(agents_app: AsyncClient):
    """POST /clients/test-client/agents with valid body returns 201."""
    response = await agents_app.post(_BASE, json=_VALID_AGENT)
    assert response.status_code == 201
    data = response.json()
    assert data["slug"] == "test-agent"
    assert data["name"] == "Test Agent"
    assert data["voice_id"] == "voice-abc123"
    assert data["client_id"] == "test-client"
    assert data["is_active"] is True
    assert data["is_default"] is False
    assert "agent_id" in data
    assert "created_at" in data


async def test_create_agent_client_not_found_returns_404(
    agents_app_empty: AsyncClient,
):
    """POST /clients/nonexistent/agents returns 404 when client doesn't exist."""
    response = await agents_app_empty.post(_BASE_EMPTY, json=_VALID_AGENT)
    assert response.status_code == 404
    data = response.json()
    assert data["detail"]["error"] == "client not found"


async def test_create_agent_duplicate_slug_returns_409(agents_app: AsyncClient):
    """POST with duplicate slug for same client returns 409 Conflict."""
    # Create first agent
    r1 = await agents_app.post(_BASE, json=_VALID_AGENT)
    assert r1.status_code == 201
    # Attempt duplicate slug
    response = await agents_app.post(_BASE, json=_VALID_AGENT)
    assert response.status_code == 409
    data = response.json()
    assert "slug" in data["detail"]["error"]


async def test_create_agent_invalid_tools_returns_422(agents_app: AsyncClient):
    """POST with unknown tool name (as list) returns 422."""
    response = await agents_app.post(
        _BASE,
        json={
            **_VALID_AGENT,
            "tools_enabled": ["nonexistent_tool"],
        },
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Task 3.1: GET single — /api/v1/clients/{client_id}/agents/{agent_id}
# ---------------------------------------------------------------------------


async def test_get_agent_returns_200(agents_app: AsyncClient):
    """GET /clients/test-client/agents/{agent_id} returns 200 with agent data."""
    create_resp = await agents_app.post(_BASE, json=_VALID_AGENT)
    assert create_resp.status_code == 201
    agent_id = create_resp.json()["agent_id"]

    response = await agents_app.get(f"{_BASE}/{agent_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["agent_id"] == agent_id
    assert data["slug"] == "test-agent"
    assert data["client_id"] == "test-client"


async def test_get_agent_not_found_returns_404(agents_app: AsyncClient):
    """GET /clients/test-client/agents/nonexistent returns 404."""
    response = await agents_app.get(f"{_BASE}/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    data = response.json()
    assert data["detail"]["error"] == "agent not found"


# ---------------------------------------------------------------------------
# Task 3.2: PATCH /{agent_id}
# ---------------------------------------------------------------------------


async def test_patch_agent_returns_200_with_updated_fields(agents_app: AsyncClient):
    """PATCH /clients/test-client/agents/{agent_id} updates only provided fields."""
    create_resp = await agents_app.post(_BASE, json=_VALID_AGENT)
    assert create_resp.status_code == 201
    agent_id = create_resp.json()["agent_id"]

    patch_resp = await agents_app.patch(
        f"{_BASE}/{agent_id}",
        json={"name": "Updated Name"},
    )
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    assert data["name"] == "Updated Name"
    assert data["slug"] == "test-agent"  # unchanged
    assert data["voice_id"] == "voice-abc123"  # unchanged


async def test_patch_agent_not_found_returns_404(agents_app: AsyncClient):
    """PATCH /clients/test-client/agents/nonexistent returns 404."""
    response = await agents_app.patch(
        f"{_BASE}/00000000-0000-0000-0000-000000000000",
        json={"name": "Ghost"},
    )
    assert response.status_code == 404
    data = response.json()
    assert data["detail"]["error"] == "agent not found"


# ---------------------------------------------------------------------------
# Task 3.2: POST /{agent_id}/deactivate
# ---------------------------------------------------------------------------


async def test_deactivate_agent_returns_200(agents_app: AsyncClient):
    """POST /deactivate on non-default agent sets is_active=False."""
    create_resp = await agents_app.post(_BASE, json=_VALID_AGENT)
    assert create_resp.status_code == 201
    agent_id = create_resp.json()["agent_id"]

    resp = await agents_app.post(f"{_BASE}/{agent_id}/deactivate")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_active"] is False
    assert data["agent_id"] == agent_id


async def test_deactivate_sole_default_agent_returns_409(agents_app: AsyncClient):
    """POST /deactivate on the sole default agent returns 409 (guard error)."""
    list_resp = await agents_app.get(_BASE)
    assert list_resp.status_code == 200
    agents = list_resp.json()
    default_agent = next(a for a in agents if a["is_default"])
    agent_id = default_agent["agent_id"]

    resp = await agents_app.post(f"{_BASE}/{agent_id}/deactivate")
    assert resp.status_code == 409
    data = resp.json()
    # Error must mention sole/default
    assert "sole" in data["detail"]["error"] or "default" in data["detail"]["error"]


async def test_deactivate_agent_not_found_returns_404(agents_app: AsyncClient):
    """POST /deactivate on nonexistent agent returns 404."""
    resp = await agents_app.post(
        f"{_BASE}/00000000-0000-0000-0000-000000000000/deactivate"
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Task 3.2: POST /{agent_id}/make-default
# ---------------------------------------------------------------------------


async def test_make_default_swaps_correctly(agents_app: AsyncClient):
    """POST /make-default swaps the default agent atomically."""
    create_resp = await agents_app.post(_BASE, json=_VALID_AGENT_2)
    assert create_resp.status_code == 201
    new_agent_id = create_resp.json()["agent_id"]

    resp = await agents_app.post(f"{_BASE}/{new_agent_id}/make-default")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_default"] is True
    assert data["agent_id"] == new_agent_id

    # Verify exactly one default in the list
    list_resp = await agents_app.get(_BASE)
    agents_list = list_resp.json()
    defaults = [a for a in agents_list if a["is_default"]]
    assert len(defaults) == 1
    assert defaults[0]["agent_id"] == new_agent_id


async def test_make_default_inactive_agent_returns_409(agents_app: AsyncClient):
    """POST /make-default on inactive agent returns 409."""
    create_resp = await agents_app.post(_BASE, json=_VALID_AGENT)
    assert create_resp.status_code == 201
    agent_id = create_resp.json()["agent_id"]

    # Deactivate it first
    deact_resp = await agents_app.post(f"{_BASE}/{agent_id}/deactivate")
    assert deact_resp.status_code == 200

    # Attempt to make inactive agent the default
    resp = await agents_app.post(f"{_BASE}/{agent_id}/make-default")
    assert resp.status_code == 409
    data = resp.json()
    assert "inactive" in data["detail"]["error"]


async def test_make_default_not_found_returns_404(agents_app: AsyncClient):
    """POST /make-default on nonexistent agent returns 404."""
    resp = await agents_app.post(
        f"{_BASE}/00000000-0000-0000-0000-000000000000/make-default"
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Task 1.2 (NEW) — elevenlabs_agent_id CRUD round-trip
# ---------------------------------------------------------------------------


async def test_create_agent_with_elevenlabs_agent_id(agents_app: AsyncClient):
    """POST /agents with elevenlabs_agent_id persists and returns the value."""
    payload = {**_VALID_AGENT, "elevenlabs_agent_id": "el_abc123"}
    response = await agents_app.post(_BASE, json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["elevenlabs_agent_id"] == "el_abc123"


async def test_create_agent_without_elevenlabs_agent_id_is_null(
    agents_app: AsyncClient,
):
    """POST /agents without elevenlabs_agent_id returns elevenlabs_agent_id=null."""
    response = await agents_app.post(_BASE, json=_VALID_AGENT)
    assert response.status_code == 201
    data = response.json()
    assert data["elevenlabs_agent_id"] is None


async def test_patch_agent_updates_elevenlabs_agent_id(agents_app: AsyncClient):
    """PATCH /agents/{id} with elevenlabs_agent_id updates the binding."""
    create_resp = await agents_app.post(_BASE, json=_VALID_AGENT)
    assert create_resp.status_code == 201
    agent_id = create_resp.json()["agent_id"]
    assert create_resp.json()["elevenlabs_agent_id"] is None

    patch_resp = await agents_app.patch(
        f"{_BASE}/{agent_id}", json={"elevenlabs_agent_id": "el_xyz"}
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["elevenlabs_agent_id"] == "el_xyz"


# ---------------------------------------------------------------------------
# Task 1.2 (NEW) — custom_llm_url computed in response
# ---------------------------------------------------------------------------


async def test_agent_response_includes_custom_llm_url(agents_app: AsyncClient):
    """GET /agents returns custom_llm_url computed from client_id."""
    response = await agents_app.post(_BASE, json=_VALID_AGENT)
    assert response.status_code == 201
    data = response.json()
    expected_url = "/api/v1/voice/test-client/custom-llm/chat/completions"
    assert data["custom_llm_url"] == expected_url


# ---------------------------------------------------------------------------
# Task 1.2 (NEW) — readiness metadata in response
# ---------------------------------------------------------------------------


async def test_agent_response_includes_readiness_flags_false_by_default(
    agents_app: AsyncClient,
):
    """POST /agents without prompt/EL ID returns is_conversation_ready=False."""
    response = await agents_app.post(_BASE, json=_VALID_AGENT)
    assert response.status_code == 201
    data = response.json()
    # New agent has no system_prompt and no elevenlabs_agent_id — not ready
    assert data["is_conversation_ready"] is False
    assert data["has_prompt"] is False
    assert data["has_elevenlabs_agent_id"] is False


async def test_agent_response_readiness_true_when_prompt_and_el_id(
    agents_app: AsyncClient,
):
    """Agent with system_prompt AND elevenlabs_agent_id is conversation-ready."""
    payload = {
        **_VALID_AGENT,
        "system_prompt": "You are Sofia, the Qora assistant.",
        "elevenlabs_agent_id": "el_ready123",
    }
    response = await agents_app.post(_BASE, json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["is_conversation_ready"] is True
    assert data["has_prompt"] is True
    assert data["has_elevenlabs_agent_id"] is True


# ---------------------------------------------------------------------------
# TTS fields — API round-trip (POST / GET / PATCH)
# ---------------------------------------------------------------------------


async def test_create_agent_returns_tts_defaults(agents_app: AsyncClient):
    """POST /agents without TTS fields returns default tts_speed/stability/similarity_boost."""
    response = await agents_app.post(_BASE, json=_VALID_AGENT)
    assert response.status_code == 201
    data = response.json()
    assert data["tts_speed"] == 0.95
    assert data["tts_stability"] == 0.4
    assert data["tts_similarity_boost"] == 0.75


async def test_create_agent_with_tts_values(agents_app: AsyncClient):
    """POST /agents with explicit TTS fields persists and returns those values."""
    payload = {
        **_VALID_AGENT,
        "tts_speed": 1.2,
        "tts_stability": 0.5,
        "tts_similarity_boost": 0.9,
    }
    response = await agents_app.post(_BASE, json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["tts_speed"] == 1.2
    assert data["tts_stability"] == 0.5
    assert data["tts_similarity_boost"] == 0.9


async def test_get_agent_returns_tts_fields(agents_app: AsyncClient):
    """GET /agents/{id} returns tts_speed, tts_stability, tts_similarity_boost."""
    create_resp = await agents_app.post(
        _BASE,
        json={**_VALID_AGENT, "tts_speed": 1.1, "tts_stability": 0.6, "tts_similarity_boost": 0.7},
    )
    assert create_resp.status_code == 201
    agent_id = create_resp.json()["agent_id"]

    get_resp = await agents_app.get(f"{_BASE}/{agent_id}")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["tts_speed"] == 1.1
    assert data["tts_stability"] == 0.6
    assert data["tts_similarity_boost"] == 0.7


async def test_patch_agent_updates_tts_speed(agents_app: AsyncClient):
    """PATCH /agents/{id} with tts_speed updates only that field.

    Uses 1.1 — within the EL valid range [0.7, 1.2].
    """
    create_resp = await agents_app.post(_BASE, json=_VALID_AGENT)
    assert create_resp.status_code == 201
    agent_id = create_resp.json()["agent_id"]

    patch_resp = await agents_app.patch(
        f"{_BASE}/{agent_id}",
        json={"tts_speed": 1.1},
    )
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    assert data["tts_speed"] == 1.1
    # Other TTS fields unchanged
    assert data["tts_stability"] == 0.4
    assert data["tts_similarity_boost"] == 0.75


async def test_create_agent_tts_out_of_range_returns_422(agents_app: AsyncClient):
    """POST /agents with tts_speed outside EL valid range [0.7, 1.2] returns 422.

    0.1 is below the EL minimum (0.7) and was the value that triggered 1008 rejections.
    """
    response = await agents_app.post(
        _BASE,
        json={**_VALID_AGENT, "tts_speed": 0.1},
    )
    assert response.status_code == 422


async def test_create_agent_tts_speed_above_max_returns_422(agents_app: AsyncClient):
    """POST /agents with tts_speed=1.5 (above EL max 1.2) returns 422."""
    response = await agents_app.post(
        _BASE,
        json={**_VALID_AGENT, "tts_speed": 1.5},
    )
    assert response.status_code == 422


async def test_patch_agent_tts_out_of_range_returns_422(agents_app: AsyncClient):
    """PATCH /agents/{id} with tts_stability=-0.1 (out of range) returns 422."""
    create_resp = await agents_app.post(_BASE, json=_VALID_AGENT)
    assert create_resp.status_code == 201
    agent_id = create_resp.json()["agent_id"]

    patch_resp = await agents_app.patch(
        f"{_BASE}/{agent_id}",
        json={"tts_stability": -0.1},
    )
    assert patch_resp.status_code == 422


# ---------------------------------------------------------------------------
# Boundary: valid 0.0 values must NOT be lost through API round-trip
# ---------------------------------------------------------------------------


async def test_create_agent_tts_stability_zero_is_preserved(agents_app: AsyncClient):
    """POST /agents with tts_stability=0.0 must return exactly 0.0, not the default 0.4.

    Regression: _agent_to_response used `value or default` which replaced 0.0 with the
    default because 0.0 is falsy in Python. Fixed to use explicit None check.
    """
    payload = {**_VALID_AGENT, "tts_stability": 0.0, "tts_similarity_boost": 0.0}
    response = await agents_app.post(_BASE, json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["tts_stability"] == 0.0, (
        f"Expected tts_stability=0.0 but got {data['tts_stability']}. "
        "Likely caused by `or default` pattern in _agent_to_response()"
    )
    assert data["tts_similarity_boost"] == 0.0, (
        f"Expected tts_similarity_boost=0.0 but got {data['tts_similarity_boost']}. "
        "Likely caused by `or default` pattern in _agent_to_response()"
    )


async def test_patch_agent_tts_stability_to_zero_is_preserved(agents_app: AsyncClient):
    """PATCH /agents/{id} with tts_stability=0.0 must return 0.0 on GET.

    Triangulation: ensures the fix works across update path too, not just create.
    """
    create_resp = await agents_app.post(_BASE, json=_VALID_AGENT)
    assert create_resp.status_code == 201
    agent_id = create_resp.json()["agent_id"]

    patch_resp = await agents_app.patch(
        f"{_BASE}/{agent_id}",
        json={"tts_stability": 0.0, "tts_similarity_boost": 0.0},
    )
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    assert data["tts_stability"] == 0.0, (
        f"Expected patched tts_stability=0.0 but got {data['tts_stability']}"
    )
    assert data["tts_similarity_boost"] == 0.0, (
        f"Expected patched tts_similarity_boost=0.0 but got {data['tts_similarity_boost']}"
    )
