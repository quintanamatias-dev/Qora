"""Unit tests for agent-scoped routing on the custom-LLM webhook (Phase 4a).

Covers:
- agent-scoped route reaches a non-default agent (D1)
- agent-scoped route rejects a mismatched client/agent pair
- legacy routes fail closed for 0/>1 active agents (D2)
- legacy routes succeed + log custom_llm_legacy_route_used for a single-active-agent client
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio
import respx
from httpx import AsyncClient, ASGITransport, Response
from pydantic import SecretStr


def _make_sse_chunk(content: str | None = None, finish_reason: str | None = None) -> bytes:
    choice: dict = {"index": 0, "delta": {}, "finish_reason": finish_reason}
    if content is not None:
        choice["delta"]["content"] = content
    payload = {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "choices": [choice],
    }
    return f"data: {json.dumps(payload)}\n\n".encode()


def _make_sse_done() -> bytes:
    return b"data: [DONE]\n\n"


def _build_simple_stream(*tokens: str) -> bytes:
    chunks = b""
    for token in tokens:
        chunks += _make_sse_chunk(content=token)
    chunks += _make_sse_chunk(finish_reason="stop")
    chunks += _make_sse_done()
    return chunks


def _valid_body(lead_id: str = "lead-quintana-001", conversation_id: str = "conv-001") -> dict:
    return {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "Hola"}],
        "stream": True,
        "elevenlabs_extra_body": {
            "lead_id": lead_id,
            "conversation_id": conversation_id,
        },
    }


@pytest_asyncio.fixture
async def two_agent_app_client(tmp_path: Path):
    """quintana-seguros with two active agents: the seeded default + 'second-agent'."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test-openai"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/webhook_two_agent_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations

    await _init_db_with_migrations(db_module, settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana, create_agent
        from app.leads.service import seed_leads

        await seed_quintana(sess)
        await seed_leads(sess)
        second = await create_agent(
            sess,
            client_id="quintana-seguros",
            slug="second-agent",
            name="SecondAgent",
            voice_id="v-second",
            system_prompt="SECOND_AGENT_UNIQUE_SYSTEM_PROMPT_MARKER",
        )
        second_agent_id = second.id
        await sess.commit()

    from app.voice.webhook import router as webhook_router
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.state.settings = settings
    test_app.include_router(webhook_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        yield client, second_agent_id

    await db_module.close_db()


@pytest_asyncio.fixture
async def single_agent_app_client(tmp_path: Path):
    """qora-demo with exactly one active agent."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test-openai"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/webhook_single_agent_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations

    await _init_db_with_migrations(db_module, settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_qora_demo

        await seed_qora_demo(sess)
        await sess.commit()

    from app.voice.webhook import router as webhook_router
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.state.settings = settings
    test_app.include_router(webhook_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        yield client

    await db_module.close_db()


# ---------------------------------------------------------------------------
# D1 — Agent-scoped route reaches a non-default agent
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_agent_scoped_route_reaches_non_default_agent(two_agent_app_client):
    """POST to the agent-scoped route for the SECOND agent uses that agent's config."""
    client, second_agent_id = two_agent_app_client

    captured_requests = []

    def side_effect(request):
        captured_requests.append(json.loads(request.content))
        return Response(
            200,
            content=_build_simple_stream("Hola"),
            headers={"content-type": "text/event-stream"},
        )

    respx.post("https://api.openai.com/v1/chat/completions").mock(side_effect=side_effect)

    response = await client.post(
        f"/api/v1/voice/quintana-seguros/agents/{second_agent_id}/custom-llm/chat/completions",
        json=_valid_body(conversation_id="conv-agent-scoped-001"),
    )

    assert response.status_code == 200, response.text
    assert captured_requests, "no request reached OpenAI"
    system_message = next(
        m["content"] for m in captured_requests[0]["messages"] if m["role"] == "system"
    )
    assert "SECOND_AGENT_UNIQUE_SYSTEM_PROMPT_MARKER" in system_message


@pytest.mark.asyncio
async def test_agent_scoped_route_rejects_mismatched_client_agent_pair(
    two_agent_app_client,
):
    """agent_id belonging to a different client than the path client_id → explicit error."""
    client, second_agent_id = two_agent_app_client

    response = await client.post(
        f"/api/v1/voice/some-other-client/agents/{second_agent_id}/custom-llm/chat/completions",
        json=_valid_body(conversation_id="conv-agent-scoped-mismatch"),
    )

    assert response.status_code == 404
    assert response.status_code != 500


# ---------------------------------------------------------------------------
# D2 — Legacy routes fail closed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_path_route_fails_closed_for_multi_agent_client(two_agent_app_client):
    client, _second_agent_id = two_agent_app_client

    response = await client.post(
        "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
        json=_valid_body(conversation_id="conv-legacy-ambiguous"),
    )

    assert response.status_code == 409, response.text
    assert response.status_code != 500


@respx.mock
@pytest.mark.asyncio
async def test_legacy_path_route_succeeds_for_single_active_agent_client(
    single_agent_app_client,
):
    from structlog.testing import capture_logs

    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(
            200,
            content=_build_simple_stream("Hola"),
            headers={"content-type": "text/event-stream"},
        )
    )

    with capture_logs() as cap:
        response = await single_agent_app_client.post(
            "/api/v1/voice/qora-demo/custom-llm/chat/completions",
            json=_valid_body(lead_id="", conversation_id="conv-legacy-single-001"),
        )

    assert response.status_code == 200, response.text
    legacy_logs = [e for e in cap if e.get("event") == "custom_llm_legacy_route_used"]
    assert legacy_logs, f"Expected custom_llm_legacy_route_used log, got: {[e.get('event') for e in cap]}"
    assert legacy_logs[0].get("client_id") == "qora-demo"
    assert "route" in legacy_logs[0]
