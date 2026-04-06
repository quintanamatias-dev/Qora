"""Unit tests for tools dispatcher.

RED: References app.tools.dispatcher which is not yet implemented.
Covers: tool routing, error handling for unknown tools.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db(tmp_path: Path):
    """DB module with seeded Quintana + test leads."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/dispatcher_test.db",
    )
    await db_module.init_db(settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import seed_leads

        await seed_quintana(sess)
        await seed_leads(sess)
        await sess.commit()

    yield db_module
    await db_module.close_db()


# ---------------------------------------------------------------------------
# T5.1: Dispatcher tests
# ---------------------------------------------------------------------------


async def test_dispatcher_routes_get_lead_details(db):
    """dispatch_tool routes 'get_lead_details' to the correct handler."""
    from app.tools.dispatcher import dispatch_tool

    async with db.async_session_factory() as sess:
        result = await dispatch_tool(
            tool_name="get_lead_details",
            tool_args={"lead_id": "lead-quintana-001"},
            client_id="quintana-seguros",
            lead_id="lead-quintana-001",
            session=sess,
        )

    assert "error" not in result
    assert result["id"] == "lead-quintana-001"


async def test_dispatcher_routes_mark_not_interested(db):
    """dispatch_tool routes 'mark_not_interested' to the correct handler."""
    from app.tools.dispatcher import dispatch_tool

    async with db.async_session_factory() as sess:
        result = await dispatch_tool(
            tool_name="mark_not_interested",
            tool_args={
                "lead_id": "lead-quintana-003",
                "reason": "Ya tiene seguro",
            },
            client_id="quintana-seguros",
            lead_id="lead-quintana-003",
            session=sess,
        )

    assert "error" not in result
    assert result["status"] == "not_interested"


async def test_dispatcher_returns_error_for_unknown_tool(db):
    """dispatch_tool returns error dict for unknown tool name."""
    from app.tools.dispatcher import dispatch_tool

    async with db.async_session_factory() as sess:
        result = await dispatch_tool(
            tool_name="unknown_tool",
            tool_args={},
            client_id="quintana-seguros",
            lead_id=None,
            session=sess,
        )

    assert "error" in result
    assert "unknown_tool" in result["error"]
