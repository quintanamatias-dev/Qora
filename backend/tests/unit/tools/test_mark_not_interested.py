"""Unit tests for mark_not_interested tool.

RED: References app.tools.mark_not_interested which is not yet implemented.
Covers: CAP-4 mark_not_interested scenarios.
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
    """DB module with seeded Quintana + test leads."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/not_interested_test.db",
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
# T5.3: mark_not_interested tests
# ---------------------------------------------------------------------------


async def test_mark_not_interested_transitions_status(db):
    """mark_not_interested sets lead status to 'not_interested' (CAP-4)."""
    from app.tools.mark_not_interested import mark_not_interested

    async with db.async_session_factory() as sess:
        # lead-quintana-003 is in 'called' state
        result = await mark_not_interested(
            session=sess,
            lead_id="lead-quintana-003",
            reason="Ya tiene seguro con otra compañía",
        )

    assert "error" not in result
    assert result["status"] == "not_interested"


async def test_mark_not_interested_saves_reason_in_notes(db):
    """mark_not_interested saves the reason in notes (CAP-4)."""
    from app.tools.mark_not_interested import mark_not_interested
    from app.leads.service import get_lead

    reason = "No le interesa cambiar de aseguradora por ahora"

    async with db.async_session_factory() as sess:
        result = await mark_not_interested(
            session=sess,
            lead_id="lead-quintana-003",
            reason=reason,
        )
        assert "error" not in result

        lead = await get_lead(sess, "lead-quintana-003")
        assert lead.notes is not None
        assert reason in lead.notes


async def test_mark_not_interested_lead_not_deleted(db):
    """Marking not interested NEVER deletes the lead (CAP-4)."""
    from app.tools.mark_not_interested import mark_not_interested
    from app.leads.service import get_lead

    async with db.async_session_factory() as sess:
        await mark_not_interested(
            session=sess,
            lead_id="lead-quintana-003",
            reason="No está interesado",
        )
        await sess.commit()

    async with db.async_session_factory() as sess:
        lead = await get_lead(sess, "lead-quintana-003")
        assert lead is not None  # Lead still exists


async def test_mark_not_interested_missing_reason_returns_error(db):
    """mark_not_interested requires a reason — returns error if missing."""
    from app.tools.mark_not_interested import mark_not_interested

    async with db.async_session_factory() as sess:
        result = await mark_not_interested(
            session=sess,
            lead_id="lead-quintana-003",
            reason="",
        )

    assert "error" in result
