"""Unit tests for tenants service — CRUD, unknown tenant, seed guard.

RED: References app.tenants.models and app.tenants.service which do NOT exist yet.
These tests define the contract before implementation.
"""

from __future__ import annotations

import pytest_asyncio
from pathlib import Path
from pydantic import SecretStr

from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def session(tmp_path: Path):
    """Provide an isolated async session for each test."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/tenants_test.db",
    )
    await db_module.init_db(settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        yield sess

    await db_module.close_db()


# ---------------------------------------------------------------------------
# Test: create_client + get_client
# ---------------------------------------------------------------------------


async def test_create_client_persists_record(session: AsyncSession):
    """create_client() persists a Client record that can be retrieved by id."""
    from app.tenants.service import create_client, get_client

    client = await create_client(
        session,
        id="test-broker",
        name="Test Broker SA",
        broker_name="Test Broker SA",
        agent_name="TestAgent",
        voice_id="voice-abc123",
    )

    assert client.id == "test-broker"
    assert client.name == "Test Broker SA"
    assert client.broker_name == "Test Broker SA"
    assert client.agent_name == "TestAgent"
    assert client.voice_id == "voice-abc123"
    assert client.is_active is True

    # Fetch by id and verify round-trip
    fetched = await get_client(session, "test-broker")
    assert fetched is not None
    assert fetched.id == "test-broker"
    assert fetched.name == "Test Broker SA"


async def test_get_client_returns_none_for_missing_id(session: AsyncSession):
    """get_client() returns None when the id does not exist."""
    from app.tenants.service import get_client

    result = await get_client(session, "nonexistent-id")
    assert result is None


# ---------------------------------------------------------------------------
# Test: get_client_by_name
# ---------------------------------------------------------------------------


async def test_get_client_by_name_finds_existing(session: AsyncSession):
    """get_client_by_name() returns the correct client by its unique name."""
    from app.tenants.service import create_client, get_client_by_name

    await create_client(
        session,
        id="broker-xyz",
        name="Broker XYZ",
        broker_name="Broker XYZ",
        agent_name="Agent",
        voice_id="v1",
    )

    found = await get_client_by_name(session, "Broker XYZ")
    assert found is not None
    assert found.id == "broker-xyz"


async def test_get_client_by_name_returns_none_for_missing(session: AsyncSession):
    """get_client_by_name() returns None when no client has that name."""
    from app.tenants.service import get_client_by_name

    result = await get_client_by_name(session, "Does Not Exist")
    assert result is None


# ---------------------------------------------------------------------------
# Test: update_client
# ---------------------------------------------------------------------------


async def test_update_client_changes_fields(session: AsyncSession):
    """update_client() persists field updates to the client record."""
    from app.tenants.service import create_client, update_client, get_client

    await create_client(
        session,
        id="updatable",
        name="Before Update",
        broker_name="Old Broker",
        agent_name="OldAgent",
        voice_id="old-voice",
    )

    updated = await update_client(
        session,
        client_id="updatable",
        name="After Update",
        broker_name="New Broker",
    )

    assert updated is not None
    assert updated.name == "After Update"
    assert updated.broker_name == "New Broker"
    # Unchanged field must stay the same
    assert updated.agent_name == "OldAgent"

    # Verify persistence (re-fetch)
    fetched = await get_client(session, "updatable")
    assert fetched is not None
    assert fetched.name == "After Update"


async def test_update_client_returns_none_for_missing(session: AsyncSession):
    """update_client() returns None when the client id does not exist."""
    from app.tenants.service import update_client

    result = await update_client(session, client_id="ghost", name="Ghost")
    assert result is None


# ---------------------------------------------------------------------------
# Test: Quintana Seguros seed
# ---------------------------------------------------------------------------


async def test_seed_quintana_creates_client(session: AsyncSession):
    """seed_quintana() creates the Quintana Seguros client if it does not exist."""
    from app.tenants.service import seed_quintana, get_client

    await seed_quintana(session)

    client = await get_client(session, "quintana-seguros")
    assert client is not None
    assert client.broker_name == "Quintana Seguros"
    assert client.agent_name == "Jaumpablo"
    assert client.voice_id == "pNInz6obpgDQGcFmaJgB"


async def test_seed_quintana_is_idempotent(session: AsyncSession):
    """seed_quintana() called twice does not raise and does not duplicate."""
    from app.tenants.service import seed_quintana
    from sqlalchemy import select
    from app.tenants.models import Client

    await seed_quintana(session)
    await seed_quintana(session)  # second call — must not error or duplicate

    result = await session.execute(
        select(Client).where(Client.id == "quintana-seguros")
    )
    clients = result.scalars().all()
    assert len(clients) == 1  # exactly one record, not two
