"""Unit tests for get_lead_details tool.

RED: References app.tools.get_lead_details which is not yet implemented.
Covers: CAP-4 get_lead_details scenarios.
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
    """DB module with seeded Quintana + test lead."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/tools_test.db",
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
# T5.1: get_lead_details tests
# ---------------------------------------------------------------------------


async def test_get_lead_details_returns_full_record(db):
    """get_lead_details returns full lead data as dict (CAP-4)."""
    from app.tools.get_lead_details import get_lead_details

    async with db.async_session_factory() as sess:
        result = await get_lead_details(
            session=sess,
            lead_id="lead-quintana-001",
        )

    assert result is not None
    assert "error" not in result
    assert result["id"] == "lead-quintana-001"
    assert result["name"] == "Carlos Méndez"
    assert result["car_make"] == "Toyota"
    assert result["car_model"] == "Corolla"
    assert result["car_year"] == 2021
    assert result["status"] == "new"


async def test_get_lead_details_increments_call_count(db):
    """get_lead_details increments call_count and sets last_called_at (CAP-4)."""
    from app.tools.get_lead_details import get_lead_details

    async with db.async_session_factory() as sess:
        # First call
        result = await get_lead_details(sess, lead_id="lead-quintana-001")
        assert result["call_count"] == 1
        assert result["last_called_at"] is not None

        # Flush to persist
        await sess.commit()

    async with db.async_session_factory() as sess:
        # Second call
        result2 = await get_lead_details(sess, lead_id="lead-quintana-001")
        assert result2["call_count"] == 2


async def test_get_lead_details_not_found_returns_error(db):
    """get_lead_details returns error dict for unknown lead_id (CAP-4)."""
    from app.tools.get_lead_details import get_lead_details

    async with db.async_session_factory() as sess:
        result = await get_lead_details(sess, lead_id="ghost-lead-000")

    assert result == {"error": "lead_not_found"}
