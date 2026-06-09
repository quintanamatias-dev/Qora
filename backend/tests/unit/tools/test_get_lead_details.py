"""Unit tests for get_lead_details tool.

RED: References app.tools.get_lead_details which is not yet implemented.
Covers: CAP-4 get_lead_details scenarios.
"""

from __future__ import annotations

from pathlib import Path

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
    """get_lead_details returns full lead data as dict (CAP-4).

    dynamic-lead-fields WU-7: car data is now in custom_fields, not legacy ORM columns.
    Legacy columns (car_make, car_model, car_year) remain in the response for backward compat
    but are None when no legacy value was written (new seed path uses custom_fields only).
    """
    from app.tools.get_lead_details import get_lead_details

    async with db.async_session_factory() as sess:
        result = await get_lead_details(
            session=sess,
            lead_id="lead-quintana-001",
            client_id="quintana-seguros",
        )

    assert result is not None
    assert "error" not in result
    assert result["id"] == "lead-quintana-001"
    assert result["name"] == "Carlos Méndez"
    assert result["status"] == "new"
    # WU-7: car data comes from custom_fields, not legacy ORM columns
    cf = result.get("custom_fields", {})
    assert cf.get("car_make") == "Toyota", (
        f"car_make must be in custom_fields. Got: {cf}"
    )
    assert cf.get("car_model") == "Corolla"
    assert cf.get("car_year") == "2021"  # stored as TEXT in custom_fields


async def test_get_lead_details_returns_call_count_from_lead_record(db):
    """get_lead_details returns call_count from the DB record (read-only after Task 1.6).

    Task 1.6: call_count increment MOVED to initiation.py.
    get_lead_details is now a pure read — it returns the current call_count without
    incrementing it.

    GIVEN lead with call_count=0
    WHEN get_lead_details is called twice
    THEN both calls return call_count=0 (not incremented by the tool)
    """
    from app.tools.get_lead_details import get_lead_details

    async with db.async_session_factory() as sess:
        result1 = await get_lead_details(sess, lead_id="lead-quintana-001")
        await sess.commit()

    async with db.async_session_factory() as sess:
        result2 = await get_lead_details(sess, lead_id="lead-quintana-001")

    # Both calls should return the same call_count (no side effect)
    assert result1.get("call_count") == 0, (
        f"get_lead_details must not increment call_count. Got: {result1.get('call_count')}"
    )
    assert result2.get("call_count") == 0, (
        f"Second call should also return 0. Got: {result2.get('call_count')}"
    )


async def test_get_lead_details_not_found_returns_error(db):
    """get_lead_details returns error dict for unknown lead_id (CAP-4)."""
    from app.tools.get_lead_details import get_lead_details

    async with db.async_session_factory() as sess:
        result = await get_lead_details(sess, lead_id="ghost-lead-000")

    assert result == {"error": "lead_not_found"}


# ---------------------------------------------------------------------------
# Task 1.6 RED — get_lead_details must NOT increment call_count
# Design decision: call_count increment belongs in initiation.py (canonical
# "call started" event). Side-effects in a query tool violate least-surprise.
# ---------------------------------------------------------------------------


async def test_get_lead_details_does_not_increment_call_count(db):
    """get_lead_details MUST NOT increment call_count after Task 1.6 refactor.

    GIVEN a lead with call_count=0
    WHEN get_lead_details is called
    THEN call_count in DB remains 0 (not incremented)
    AND last_called_at is NOT set
    """
    from app.tools.get_lead_details import get_lead_details
    from app.leads.service import get_lead

    async with db.async_session_factory() as sess:
        lead_before = await get_lead(sess, "lead-quintana-001")
        count_before = lead_before.call_count

    async with db.async_session_factory() as sess:
        await get_lead_details(sess, lead_id="lead-quintana-001")
        await sess.commit()

    async with db.async_session_factory() as sess:
        lead_after = await get_lead(sess, "lead-quintana-001")

    assert lead_after.call_count == count_before, (
        f"get_lead_details must NOT increment call_count. "
        f"Was {count_before}, now {lead_after.call_count}"
    )
    assert lead_after.last_called_at is None, (
        "get_lead_details must NOT set last_called_at"
    )
