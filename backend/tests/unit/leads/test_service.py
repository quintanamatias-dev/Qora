"""Unit tests for lead service — CRUD, seed guard, tenant scoping, state transitions."""

from __future__ import annotations

import pytest
import pytest_asyncio
from pathlib import Path
from pydantic import SecretStr

from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_session(tmp_path: Path):
    """Session with Quintana Seguros client and 5 test leads pre-loaded."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/leads_test.db",
    )
    await db_module.init_db(settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import seed_leads

        await seed_quintana(sess)
        await seed_leads(sess)
        await sess.commit()

        yield sess

    await db_module.close_db()


@pytest_asyncio.fixture
async def empty_session(tmp_path: Path):
    """Session with Quintana client but NO leads."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/leads_empty_test.db",
    )
    await db_module.init_db(settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana

        await seed_quintana(sess)
        await sess.commit()

        yield sess

    await db_module.close_db()


# ---------------------------------------------------------------------------
# Seed data tests
# ---------------------------------------------------------------------------


async def test_seed_leads_creates_five_leads(seeded_session: AsyncSession):
    """seed_leads() creates exactly 5 leads for quintana-seguros."""
    from app.leads.service import list_leads_for_client

    leads = await list_leads_for_client(seeded_session, "quintana-seguros")
    assert len(leads) == 5


async def test_seed_leads_covers_required_statuses(seeded_session: AsyncSession):
    """Seed data has at least 2 new, 1 called, 1 interested, 1 not_interested."""
    from app.leads.service import list_leads_for_client

    leads = await list_leads_for_client(seeded_session, "quintana-seguros")
    statuses = [lead.status for lead in leads]

    new_count = statuses.count("new")
    called_count = statuses.count("called")
    interested_count = statuses.count("interested")
    not_interested_count = statuses.count("not_interested")

    assert new_count >= 2, f"Expected >= 2 new leads, got {new_count}"
    assert called_count >= 1, f"Expected >= 1 called lead, got {called_count}"
    assert (
        interested_count >= 1
    ), f"Expected >= 1 interested lead, got {interested_count}"
    assert (
        not_interested_count >= 1
    ), f"Expected >= 1 not_interested lead, got {not_interested_count}"


async def test_seed_leads_is_idempotent(empty_session: AsyncSession):
    """seed_leads() called twice does not duplicate leads."""
    from app.leads.service import seed_leads, list_leads_for_client

    await seed_leads(empty_session)
    await seed_leads(empty_session)  # second call
    await empty_session.flush()

    leads = await list_leads_for_client(empty_session, "quintana-seguros")
    assert len(leads) == 5  # exactly 5, not 10


# ---------------------------------------------------------------------------
# CRUD tests
# ---------------------------------------------------------------------------


async def test_get_lead_returns_correct_record(seeded_session: AsyncSession):
    """get_lead() returns the lead with matching id."""
    from app.leads.service import list_leads_for_client, get_lead

    leads = await list_leads_for_client(seeded_session, "quintana-seguros")
    target = leads[0]

    fetched = await get_lead(seeded_session, target.id)
    assert fetched is not None
    assert fetched.id == target.id
    assert fetched.name == target.name


async def test_get_lead_returns_none_for_missing(seeded_session: AsyncSession):
    """get_lead() returns None for a non-existent id."""
    from app.leads.service import get_lead

    result = await get_lead(seeded_session, "ghost-id-00000")
    assert result is None


async def test_list_leads_scoped_to_client(
    seeded_session: AsyncSession, tmp_path: Path
):
    """list_leads_for_client() does not return leads from a different client."""
    from app.leads.service import list_leads_for_client
    from app.tenants.service import create_client

    # Create second client
    await create_client(
        seeded_session,
        id="other-broker",
        name="Other Broker SA",
        agent_name="OtherAgent",
        voice_id="other-voice",
    )
    await seeded_session.flush()

    # Other client has no leads
    other_leads = await list_leads_for_client(seeded_session, "other-broker")
    assert len(other_leads) == 0

    # Quintana still has 5
    quintana_leads = await list_leads_for_client(seeded_session, "quintana-seguros")
    assert len(quintana_leads) == 5


# ---------------------------------------------------------------------------
# State transition tests via service
# ---------------------------------------------------------------------------


async def test_transition_new_to_called_succeeds(seeded_session: AsyncSession):
    """Service allows new → called transition and persists it."""
    from app.leads.service import list_leads_for_client, transition_lead_status

    new_leads = [
        item
        for item in await list_leads_for_client(seeded_session, "quintana-seguros")
        if item.status == "new"
    ]
    assert new_leads, "Need at least one 'new' lead for this test"
    lead = new_leads[0]

    updated = await transition_lead_status(seeded_session, lead.id, "called")
    assert updated is not None
    assert updated.status == "called"


async def test_transition_invalid_raises_409(seeded_session: AsyncSession):
    """Service rejects new → not_interested with InvalidTransitionError."""
    from app.leads.service import list_leads_for_client, transition_lead_status
    from app.leads.service import InvalidTransitionError

    new_leads = [
        item
        for item in await list_leads_for_client(seeded_session, "quintana-seguros")
        if item.status == "new"
    ]
    assert new_leads, "Need at least one 'new' lead"
    lead = new_leads[0]

    with pytest.raises(InvalidTransitionError) as exc_info:
        await transition_lead_status(seeded_session, lead.id, "not_interested")

    err = exc_info.value
    assert err.from_status == "new"
    assert err.to_status == "not_interested"
