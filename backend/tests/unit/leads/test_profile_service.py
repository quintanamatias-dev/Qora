"""Unit tests for lead profile query service functions (Issue #36 Phase 2).

Tests cover:
- get_active_profile_facts() — active-row filtering (superseded_at IS NULL)
- get_interest_history() — newest-first ordering, limit
- get_facts_by_namespace() — prefix filtering, active rows only
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def profile_db(tmp_path: Path):
    """Isolated SQLite DB with quintana-seguros + one test lead."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/profile_service_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations
    await _init_db_with_migrations(db_module, settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead

        await seed_quintana(sess)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Profile Service Lead",
            phone="+5411099999",
            lead_id="test-lead-profile-svc-001",
        )
        await sess.commit()

    yield db_module

    await db_module.close_db()


async def _insert_profile_fact(
    db_module,
    *,
    lead_id: str,
    fact_key: str,
    fact_value: str,
    superseded_at=None,
    recorded_at=None,
) -> str:
    """Helper: directly insert a LeadProfileFact row."""
    from app.leads.models import LeadProfileFact

    row_id = str(uuid.uuid4())
    async with db_module.async_session_factory() as sess:
        row = LeadProfileFact(
            id=row_id,
            lead_id=lead_id,
            fact_key=fact_key,
            fact_value=fact_value,
            superseded_at=superseded_at,
            recorded_at=recorded_at or datetime.now(timezone.utc),
        )
        sess.add(row)
        await sess.commit()
    return row_id


async def _insert_interest_history(
    db_module, *, lead_id: str, interest_level: int, recorded_at=None
) -> str:
    """Helper: directly insert a LeadInterestHistory row."""
    from app.leads.models import LeadInterestHistory

    row_id = str(uuid.uuid4())
    async with db_module.async_session_factory() as sess:
        row = LeadInterestHistory(
            id=row_id,
            lead_id=lead_id,
            interest_level=interest_level,
            recorded_at=recorded_at or datetime.now(timezone.utc),
        )
        sess.add(row)
        await sess.commit()
    return row_id


# ---------------------------------------------------------------------------
# get_active_profile_facts — active-row filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_active_profile_facts_returns_only_active_rows(profile_db):
    """Issue #36 Phase 2: get_active_profile_facts returns only rows with superseded_at IS NULL.

    GIVEN a lead with 3 profile: rows, 1 superseded
    WHEN get_active_profile_facts(db, lead_id) is called
    THEN only 2 active rows are returned.
    """
    from app.leads.service import get_active_profile_facts

    lead_id = "test-lead-profile-svc-001"
    now = datetime.now(timezone.utc)

    await _insert_profile_fact(
        profile_db, lead_id=lead_id, fact_key="profile:married", fact_value="married"
    )
    await _insert_profile_fact(
        profile_db, lead_id=lead_id, fact_key="profile:retired", fact_value="retired"
    )
    # Superseded row — must NOT appear
    await _insert_profile_fact(
        profile_db,
        lead_id=lead_id,
        fact_key="profile:old fact",
        fact_value="old fact",
        superseded_at=now - timedelta(hours=1),
    )

    async with profile_db.async_session_factory() as sess:
        rows = await get_active_profile_facts(sess, lead_id)

    assert len(rows) == 2, f"Expected 2 active rows, got {len(rows)}: {rows}"
    keys = {r["fact_key"] for r in rows}
    assert keys == {"profile:married", "profile:retired"}


@pytest.mark.asyncio
async def test_get_active_profile_facts_returns_serialized_dicts(profile_db):
    """Issue #36 Phase 2: get_active_profile_facts returns list of dicts with correct keys."""
    from app.leads.service import get_active_profile_facts

    lead_id = "test-lead-profile-svc-001"
    await _insert_profile_fact(
        profile_db, lead_id=lead_id, fact_key="pain:high price", fact_value="high price"
    )

    async with profile_db.async_session_factory() as sess:
        rows = await get_active_profile_facts(sess, lead_id)

    assert len(rows) >= 1
    row = next(r for r in rows if r["fact_key"] == "pain:high price")
    assert "fact_key" in row
    assert "fact_value" in row
    assert "recorded_at" in row
    assert row["fact_value"] == "high price"


@pytest.mark.asyncio
async def test_get_active_profile_facts_empty_lead_returns_empty_list(profile_db):
    """Issue #36 Phase 2: get_active_profile_facts returns [] for lead with no facts."""
    from app.leads.service import get_active_profile_facts

    # Create a fresh lead with no facts
    async with profile_db.async_session_factory() as sess:
        from app.leads.service import create_lead

        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Empty Facts Lead",
            phone="+5411011111",
            lead_id="test-lead-empty-facts",
        )
        await sess.commit()

    async with profile_db.async_session_factory() as sess:
        rows = await get_active_profile_facts(sess, "test-lead-empty-facts")

    assert rows == [], f"Expected [], got {rows}"


# ---------------------------------------------------------------------------
# get_interest_history — newest-first ordering, limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_interest_history_returns_newest_first(profile_db):
    """Issue #36 Phase 2: get_interest_history returns rows ordered by recorded_at DESC.

    GIVEN 3 LeadInterestHistory rows for a lead recorded at different times
    WHEN get_interest_history(db, lead_id) is called
    THEN rows are returned ordered newest first.
    """
    from app.leads.service import get_interest_history

    lead_id = "test-lead-profile-svc-001"
    now = datetime.now(timezone.utc)

    await _insert_interest_history(
        profile_db,
        lead_id=lead_id,
        interest_level=50,
        recorded_at=now - timedelta(days=3),
    )
    await _insert_interest_history(
        profile_db,
        lead_id=lead_id,
        interest_level=70,
        recorded_at=now - timedelta(days=2),
    )
    await _insert_interest_history(
        profile_db,
        lead_id=lead_id,
        interest_level=90,
        recorded_at=now - timedelta(days=1),
    )

    async with profile_db.async_session_factory() as sess:
        rows = await get_interest_history(sess, lead_id)

    assert len(rows) == 3
    # Newest first — 90, 70, 50
    assert rows[0]["interest_level"] == 90
    assert rows[1]["interest_level"] == 70
    assert rows[2]["interest_level"] == 50


@pytest.mark.asyncio
async def test_get_interest_history_respects_limit(profile_db):
    """Issue #36 Phase 2: get_interest_history respects the limit parameter (default 10).

    GIVEN 12 interest history rows
    WHEN get_interest_history(db, lead_id, limit=10) is called
    THEN at most 10 rows are returned.
    """
    from app.leads.service import get_interest_history

    lead_id = "test-lead-profile-svc-001"
    now = datetime.now(timezone.utc)

    for i in range(12):
        await _insert_interest_history(
            profile_db,
            lead_id=lead_id,
            interest_level=i * 5,
            recorded_at=now - timedelta(hours=12 - i),
        )

    async with profile_db.async_session_factory() as sess:
        rows = await get_interest_history(sess, lead_id, limit=10)

    assert len(rows) == 10, f"Expected 10 rows, got {len(rows)}"


@pytest.mark.asyncio
async def test_get_interest_history_empty_returns_empty_list(profile_db):
    """Issue #36 Phase 2: get_interest_history returns [] for lead with no history."""
    from app.leads.service import get_interest_history

    async with profile_db.async_session_factory() as sess:
        from app.leads.service import create_lead

        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="No History Lead",
            phone="+5411022222",
            lead_id="test-lead-no-history",
        )
        await sess.commit()

    async with profile_db.async_session_factory() as sess:
        rows = await get_interest_history(sess, "test-lead-no-history")

    assert rows == [], f"Expected [], got {rows}"


# ---------------------------------------------------------------------------
# get_facts_by_namespace — prefix filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_facts_by_namespace_filters_by_prefix(profile_db):
    """Issue #36 Phase 2: get_facts_by_namespace returns only rows matching prefix.

    GIVEN a lead with 'profile:' and 'pain:' rows
    WHEN get_facts_by_namespace(db, lead_id, 'pain:') is called
    THEN only 'pain:' rows are returned.
    """
    from app.leads.service import get_facts_by_namespace

    lead_id = "test-lead-profile-svc-001"

    await _insert_profile_fact(
        profile_db, lead_id=lead_id, fact_key="profile:married", fact_value="married"
    )
    await _insert_profile_fact(
        profile_db, lead_id=lead_id, fact_key="pain:high price", fact_value="high price"
    )
    await _insert_profile_fact(
        profile_db,
        lead_id=lead_id,
        fact_key="pain:no coverage",
        fact_value="no coverage",
    )

    async with profile_db.async_session_factory() as sess:
        rows = await get_facts_by_namespace(sess, lead_id, "pain:")

    assert (
        len(rows) == 2
    ), f"Expected 2 pain: rows, got {len(rows)}: {[r['fact_key'] for r in rows]}"
    for row in rows:
        assert row["fact_key"].startswith("pain:"), f"Unexpected key: {row['fact_key']}"


@pytest.mark.asyncio
async def test_get_facts_by_namespace_excludes_superseded(profile_db):
    """Issue #36 Phase 2: get_facts_by_namespace returns only active (non-superseded) rows."""
    from app.leads.service import get_facts_by_namespace

    lead_id = "test-lead-profile-svc-001"
    now = datetime.now(timezone.utc)

    await _insert_profile_fact(
        profile_db, lead_id=lead_id, fact_key="signal:will buy", fact_value="will buy"
    )
    await _insert_profile_fact(
        profile_db,
        lead_id=lead_id,
        fact_key="signal:old signal",
        fact_value="old signal",
        superseded_at=now - timedelta(hours=1),
    )

    async with profile_db.async_session_factory() as sess:
        rows = await get_facts_by_namespace(sess, lead_id, "signal:")

    assert len(rows) == 1, f"Expected 1 active signal: row, got {len(rows)}"
    assert rows[0]["fact_key"] == "signal:will buy"


# ---------------------------------------------------------------------------
# qora-profile-facts Phase 3: get_active_profile_facts returns id field (AD-4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_active_profile_facts_returns_id_field(profile_db):
    """qora-profile-facts Phase 3: get_active_profile_facts must return 'id' in each dict.

    GIVEN a lead with an active profile: fact
    WHEN get_active_profile_facts(db, lead_id) is called
    THEN each returned dict MUST contain an 'id' field (str UUID).
    The 'id' is used by GPT as target_fact_id for update/remove operations.
    """
    from app.leads.service import get_active_profile_facts

    lead_id = "test-lead-profile-svc-001"
    row_id = await _insert_profile_fact(
        profile_db,
        lead_id=lead_id,
        fact_key="profile:occupation:vendedor",
        fact_value='{"category": "occupation", "fact": "vendedor inmobiliario", "evidence": "lo dijo", "confidence": "high"}',
    )

    async with profile_db.async_session_factory() as sess:
        rows = await get_active_profile_facts(sess, lead_id)

    matching = [r for r in rows if r["fact_key"] == "profile:occupation:vendedor"]
    assert len(matching) >= 1, "Expected at least one row with the inserted fact_key"
    row = matching[0]
    assert "id" in row, (
        "get_active_profile_facts must return 'id' field in each dict "
        "(AD-4: GPT uses id as target_fact_id for update/remove)"
    )
    assert row["id"] == row_id, f"Expected id={row_id!r}, got id={row.get('id')!r}"


@pytest.mark.asyncio
async def test_get_facts_by_namespace_also_returns_id_field(profile_db):
    """qora-profile-facts Phase 3: get_facts_by_namespace must also return 'id' field.

    GIVEN a lead with a profile: fact
    WHEN get_facts_by_namespace(db, lead_id, 'profile:') is called
    THEN each returned dict MUST contain an 'id' field.
    """
    from app.leads.service import get_facts_by_namespace

    lead_id = "test-lead-profile-svc-001"
    row_id = await _insert_profile_fact(
        profile_db,
        lead_id=lead_id,
        fact_key="profile:lifestyle:runner",
        fact_value='{"category": "lifestyle", "fact": "runner", "evidence": "sale a correr", "confidence": "medium"}',
    )

    async with profile_db.async_session_factory() as sess:
        rows = await get_facts_by_namespace(sess, lead_id, "profile:")

    matching = [r for r in rows if r["fact_key"] == "profile:lifestyle:runner"]
    assert len(matching) >= 1
    row = matching[0]
    assert (
        "id" in row
    ), "get_facts_by_namespace must return 'id' field — needed for target_fact_id"
    assert row["id"] == row_id
