"""TDD tests for CRITICAL 1: tools_enabled must be list[str] in API contract.

RED: These tests will FAIL because AgentCreate/AgentUpdate/AgentResponse currently
use str (JSON string) instead of list[str].

After GREEN: POST /agents with tools_enabled=["get_lead_details"] returns 201 with
tools_enabled as a list in the response.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr, ValidationError


# ---------------------------------------------------------------------------
# Unit tests — schemas accept list[str], not JSON string
# ---------------------------------------------------------------------------


def test_agent_create_accepts_list_of_tools():
    """AgentCreate.tools_enabled must accept a list[str], not a JSON string."""
    from app.agents.schemas import AgentCreate

    agent = AgentCreate(
        slug="list-tools-agent",
        name="List Tools Agent",
        voice_id="voice-abc",
        tools_enabled=["get_lead_details"],
    )
    # tools_enabled should be a list in the schema
    assert agent.tools_enabled == ["get_lead_details"]


def test_agent_create_default_tools_is_list():
    """AgentCreate.tools_enabled default value must be a list, not a JSON string.

    Phase 2: legacy tools removed — default no longer contains register_interest,
    mark_not_interested, or schedule_followup.
    """
    from app.agents.schemas import AgentCreate

    agent = AgentCreate(slug="def-tools", name="Default Tools", voice_id="v-123")
    assert isinstance(agent.tools_enabled, list)
    assert "get_lead_details" in agent.tools_enabled
    # Phase 2: legacy tools removed from defaults
    assert "register_interest" not in agent.tools_enabled
    assert "mark_not_interested" not in agent.tools_enabled
    assert "schedule_followup" not in agent.tools_enabled
    # capture_data is in the defaults (Phase 1 addition)
    assert "capture_data" in agent.tools_enabled


def test_agent_create_invalid_tool_in_list_raises_validation_error():
    """AgentCreate raises ValidationError when list contains unknown tool."""
    from app.agents.schemas import AgentCreate

    with pytest.raises(ValidationError) as exc_info:
        AgentCreate(
            slug="test",
            name="Test",
            voice_id="v1",
            tools_enabled=["get_lead_details", "nonexistent_tool"],
        )
    assert "nonexistent_tool" in str(exc_info.value)


def test_agent_update_accepts_list_of_tools():
    """AgentUpdate.tools_enabled must accept list[str].

    Phase 2: register_interest removed; use capture_data or get_lead_details instead.
    """
    from app.agents.schemas import AgentUpdate

    update = AgentUpdate(tools_enabled=["get_lead_details", "capture_data"])
    assert update.tools_enabled == ["get_lead_details", "capture_data"]


def test_agent_update_invalid_tool_in_list_raises_validation_error():
    """AgentUpdate raises ValidationError when list contains unknown tool."""
    from app.agents.schemas import AgentUpdate

    with pytest.raises(ValidationError) as exc_info:
        AgentUpdate(tools_enabled=["bad_tool_name"])
    assert "bad_tool_name" in str(exc_info.value)


def test_agent_response_tools_enabled_is_list():
    """AgentResponse.tools_enabled must be list[str]."""
    from datetime import datetime, timezone

    from app.agents.schemas import AgentResponse

    now = datetime.now(timezone.utc)
    resp = AgentResponse(
        agent_id="uuid-1234",
        client_id="test-client",
        slug="main",
        name="Main Agent",
        voice_id="v1",
        system_prompt=None,
        knowledge_base=None,
        model="gpt-4o",
        temperature=0.7,
        max_tokens=300,
        tools_enabled=["get_lead_details"],
        is_active=True,
        is_default=True,
        created_at=now,
    )
    assert isinstance(resp.tools_enabled, list)
    assert resp.tools_enabled == ["get_lead_details"]


# ---------------------------------------------------------------------------
# Integration test — POST /agents with list returns 201 with list in response
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def tools_list_app(tmp_path: Path):
    """Isolated app for tools_enabled list contract tests."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/tools_list_test.db",
    )
    await db_module.init_db(settings)

    async with db_module.async_session_factory() as session:
        from app.tenants.service import create_client

        await create_client(
            session,
            id="tools-test-client",
            name="Tools Test Client SA",
            broker_name="Tools Test Client SA",
            agent_name="ToolsAgent",
            voice_id="voice-tools",
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


async def test_post_agent_with_list_tools_returns_201(tools_list_app: AsyncClient):
    """POST /agents with tools_enabled as a list returns 201 and list in response."""
    response = await tools_list_app.post(
        "/api/v1/clients/tools-test-client/agents",
        json={
            "slug": "list-agent",
            "name": "List Agent",
            "voice_id": "voice-abc",
            "tools_enabled": ["get_lead_details"],
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert isinstance(data["tools_enabled"], list)
    assert data["tools_enabled"] == ["get_lead_details"]


async def test_post_agent_with_full_tool_list_returns_201(tools_list_app: AsyncClient):
    """POST /agents with active tools as a list returns 201 with all tools in response.

    Phase 2: legacy tools removed. Test uses the current active tool set.
    """
    response = await tools_list_app.post(
        "/api/v1/clients/tools-test-client/agents",
        json={
            "slug": "full-tools-agent",
            "name": "Full Tools Agent",
            "voice_id": "voice-full",
            "tools_enabled": [
                "get_lead_details",
                "get_lead_profile",
                "get_lead_history",
                "capture_data",
            ],
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert isinstance(data["tools_enabled"], list)
    assert set(data["tools_enabled"]) == {
        "get_lead_details",
        "get_lead_profile",
        "get_lead_history",
        "capture_data",
    }


async def test_post_agent_with_invalid_tool_in_list_returns_422(
    tools_list_app: AsyncClient,
):
    """POST /agents with unknown tool in list returns 422."""
    response = await tools_list_app.post(
        "/api/v1/clients/tools-test-client/agents",
        json={
            "slug": "bad-tools-agent",
            "name": "Bad Tools Agent",
            "voice_id": "voice-bad",
            "tools_enabled": ["nonexistent_tool"],
        },
    )
    assert response.status_code == 422


async def test_list_agents_returns_tools_as_list(tools_list_app: AsyncClient):
    """GET /agents returns tools_enabled as list[str] for each agent."""
    response = await tools_list_app.get("/api/v1/clients/tools-test-client/agents")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    for agent in data:
        assert isinstance(agent["tools_enabled"], list)
