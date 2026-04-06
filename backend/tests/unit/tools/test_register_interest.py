"""Unit tests for register_interest tool.

RED: References app.tools.register_interest which is not yet implemented.
Covers: CAP-4 register_interest scenarios.
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
        database_url=f"sqlite+aiosqlite:///{tmp_path}/interest_test.db",
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
# T5.2: register_interest tests
# ---------------------------------------------------------------------------


async def test_register_interest_transitions_to_interested(db):
    """register_interest sets lead status to 'interested' (CAP-4)."""
    from app.tools.register_interest import register_interest

    async with db.async_session_factory() as sess:
        # lead-quintana-003 is in 'called' state (valid for interest)
        result = await register_interest(
            session=sess,
            lead_id="lead-quintana-003",
            car_make="Ford",
            car_model="Ranger",
            car_year=2022,
            current_insurance=None,
            notes="Quiere todo riesgo",
        )

    assert "error" not in result
    assert result["status"] == "interested"
    assert result["car_make"] == "Ford"
    assert result["car_model"] == "Ranger"
    assert result["car_year"] == 2022


async def test_register_interest_missing_car_make_returns_error(db):
    """register_interest returns error for missing required field car_make (CAP-4)."""
    from app.tools.register_interest import register_interest

    async with db.async_session_factory() as sess:
        result = await register_interest(
            session=sess,
            lead_id="lead-quintana-003",
            car_make=None,
            car_model="Ranger",
            car_year=2022,
        )

    assert result == {"error": "missing_field", "field": "car_make"}


async def test_register_interest_missing_car_model_returns_error(db):
    """register_interest returns error for missing required field car_model."""
    from app.tools.register_interest import register_interest

    async with db.async_session_factory() as sess:
        result = await register_interest(
            session=sess,
            lead_id="lead-quintana-003",
            car_make="Ford",
            car_model=None,
            car_year=2022,
        )

    assert result == {"error": "missing_field", "field": "car_model"}


async def test_register_interest_missing_car_year_returns_error(db):
    """register_interest returns error for missing required field car_year."""
    from app.tools.register_interest import register_interest

    async with db.async_session_factory() as sess:
        result = await register_interest(
            session=sess,
            lead_id="lead-quintana-003",
            car_make="Ford",
            car_model="Ranger",
            car_year=None,
        )

    assert result == {"error": "missing_field", "field": "car_year"}


async def test_register_interest_does_not_modify_lead_on_error(db):
    """On missing field error, lead record is NOT modified (CAP-4)."""
    from app.tools.register_interest import register_interest
    from app.leads.service import get_lead

    async with db.async_session_factory() as sess:
        original = await get_lead(sess, "lead-quintana-003")
        original_status = original.status

        result = await register_interest(
            session=sess,
            lead_id="lead-quintana-003",
            car_make=None,
            car_model="Ranger",
            car_year=2022,
        )

        # Verify error was returned
        assert "error" in result

        # Refresh lead and verify unchanged
        lead = await get_lead(sess, "lead-quintana-003")
        assert lead.status == original_status
