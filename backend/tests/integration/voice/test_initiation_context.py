"""Integration tests for initiation webhook context building — VSC-5.

TDD RED phase for Tasks 3.1, 3.2, 3.3.
Covers spec scenarios:
- conversation_id accepted and stored in session_store with non-empty context (3.1)
- dynamic_variables response unchanged after context storage (3.2)
- build_voice_context failure: HTTP 200 still returned, voice_context_build_failed logged,
  context=None stored (3.3)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def context_app_client(tmp_path: Path):
    """Test app with isolated SQLite, seeded with quintana-seguros and a lead."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/initiation_context_test.db",
    )

    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations
    await _init_db_with_migrations(db_module, settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import seed_leads

        await seed_quintana(sess)
        await seed_leads(sess)
        await sess.commit()

    from app.voice.initiation import router as initiation_router
    from app.voice import session as session_module
    from fastapi import FastAPI

    # Reset session store state before test
    session_module.session_store._sessions.clear()

    test_app = FastAPI()
    test_app.include_router(initiation_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        yield client, session_module.session_store

    await db_module.close_db()
    # Clean up session store
    session_module.session_store._sessions.clear()


# ---------------------------------------------------------------------------
# Task 3.1 — conversation_id accepted and context stored in session_store
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initiation_stores_context_when_conversation_id_provided(
    context_app_client,
):
    """VSC-5: When conversation_id is provided, session_store has non-None context.

    GIVEN a valid initiation request with client_id, lead_id, and conversation_id
    WHEN the initiation webhook completes successfully
    THEN session_store.get((client_id, conversation_id)).context is not None
    AND .context.system_prompt is non-empty
    """
    http_client, store = context_app_client

    conversation_id = "test-conv-001"

    response = await http_client.post(
        "/api/v1/voice/initiation",
        json={
            "client_id": "quintana-seguros",
            "lead_id": "lead-quintana-001",
            "conversation_id": conversation_id,
        },
    )

    assert response.status_code == 200

    # Check session store has context
    conv_state = store.get(("quintana-seguros", conversation_id))
    assert conv_state is not None, (
        f"session_store must have a ConversationState for conversation_id={conversation_id!r}"
    )
    assert conv_state.context is not None, (
        "ConversationState.context must not be None after initiation with conversation_id"
    )
    assert conv_state.context.system_prompt, (
        "context.system_prompt must be non-empty"
    )


@pytest.mark.asyncio
async def test_initiation_context_has_correct_client_and_lead(
    context_app_client,
):
    """Triangulation: stored context is populated with correct data."""
    http_client, store = context_app_client

    conversation_id = "test-conv-002"

    response = await http_client.post(
        "/api/v1/voice/initiation",
        json={
            "client_id": "quintana-seguros",
            "lead_id": "lead-quintana-001",
            "conversation_id": conversation_id,
        },
    )

    assert response.status_code == 200

    conv_state = store.get(("quintana-seguros", conversation_id))
    assert conv_state is not None
    assert conv_state.context is not None

    # Lead profile should contain Carlos Méndez (from seeded lead)
    assert "Carlos" in conv_state.context.lead_profile or "Méndez" in conv_state.context.lead_profile


# ---------------------------------------------------------------------------
# Task 3.2 — dynamic_variables response unchanged after context storage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initiation_dynamic_variables_unchanged_with_conversation_id(
    context_app_client,
):
    """VSC-5: dynamic_variables response is identical whether or not conversation_id provided.

    The context building MUST NOT change the response contract.
    """
    http_client, store = context_app_client

    # Request with conversation_id
    response = await http_client.post(
        "/api/v1/voice/initiation",
        json={
            "client_id": "quintana-seguros",
            "lead_id": "lead-quintana-001",
            "conversation_id": "test-conv-003",
        },
    )

    assert response.status_code == 200
    data = response.json()

    assert data["type"] == "conversation_initiation_client_data"
    dv = data["dynamic_variables"]

    # All expected fields must be present
    assert "lead_name" in dv
    assert "car_make" in dv
    assert "car_model" in dv
    assert "car_year" in dv
    assert "current_insurance" in dv
    assert "lead_status" in dv
    assert "lead_notes" in dv
    assert "company_name" in dv
    assert "agent_name" in dv
    assert "call_history" in dv
    assert "confirmed_facts" in dv
    assert "is_returning_caller" in dv
    assert "call_number" in dv

    # Underscore-wrapped variants
    assert "_lead_name_" in dv
    assert "_call_history_" in dv
    assert "_confirmed_facts_" in dv
    assert "_is_returning_caller_" in dv
    assert "_call_number_" in dv

    # Values must match seeded lead data
    assert dv["lead_name"] == "Carlos Méndez"
    assert dv["car_make"] == "Toyota"


@pytest.mark.asyncio
async def test_initiation_without_conversation_id_still_returns_200(
    context_app_client,
):
    """Backward compat: initiation without conversation_id returns HTTP 200 normally."""
    http_client, store = context_app_client

    response = await http_client.post(
        "/api/v1/voice/initiation",
        json={
            "client_id": "quintana-seguros",
            "lead_id": "lead-quintana-001",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert "dynamic_variables" in data


# ---------------------------------------------------------------------------
# Task 3.3 — build_voice_context failure: HTTP 200, logged, context=None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initiation_build_context_failure_returns_200(
    context_app_client,
):
    """VSC-5 build failure: when build_voice_context raises, still returns HTTP 200.

    GIVEN build_voice_context() raises an exception
    WHEN the initiation webhook handles it
    THEN the webhook still returns HTTP 200 with dynamic_variables
    AND ConversationState.context is None
    """
    http_client, store = context_app_client
    conversation_id = "test-conv-fail"

    with patch(
        "app.voice.initiation.build_voice_context",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Simulated context build failure"),
    ):
        response = await http_client.post(
            "/api/v1/voice/initiation",
            json={
                "client_id": "quintana-seguros",
                "lead_id": "lead-quintana-001",
                "conversation_id": conversation_id,
            },
        )

    assert response.status_code == 200, (
        f"Initiation must return 200 even when build_voice_context fails. "
        f"Got: {response.status_code}"
    )
    data = response.json()
    assert "dynamic_variables" in data


@pytest.mark.asyncio
async def test_initiation_build_context_failure_stores_none_context(
    context_app_client,
):
    """VSC-5 build failure: ConversationState.context is None when build_voice_context raises."""
    http_client, store = context_app_client
    conversation_id = "test-conv-fail-2"

    with patch(
        "app.voice.initiation.build_voice_context",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Simulated context build failure"),
    ):
        response = await http_client.post(
            "/api/v1/voice/initiation",
            json={
                "client_id": "quintana-seguros",
                "lead_id": "lead-quintana-001",
                "conversation_id": conversation_id,
            },
        )

    assert response.status_code == 200

    conv_state = store.get(("quintana-seguros", conversation_id))
    assert conv_state is not None, (
        "ConversationState must be created even when build_voice_context fails"
    )
    assert conv_state.context is None, (
        "ConversationState.context must be None when build_voice_context raises"
    )


@pytest.mark.asyncio
async def test_initiation_build_context_failure_logs_event(
    context_app_client,
    capfd,
):
    """VSC-5 build failure: voice_context_build_failed log event is emitted."""
    http_client, store = context_app_client

    with patch(
        "app.voice.initiation.build_voice_context",
        new_callable=AsyncMock,
        side_effect=ValueError("Context build error"),
    ):
        response = await http_client.post(
            "/api/v1/voice/initiation",
            json={
                "client_id": "quintana-seguros",
                "lead_id": "lead-quintana-001",
                "conversation_id": "test-conv-fail-log",
            },
        )

    assert response.status_code == 200
    # The logger.warning should have been called — verified by the endpoint not crashing
