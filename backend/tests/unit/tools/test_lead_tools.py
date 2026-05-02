"""Unit tests for Issue #36 agent lead query tools.

Tests cover:
- get_lead_profile handler: grouped facts, lead not found
- get_lead_history handler: returns history, empty history
- get_lead_pain_points handler: returns pain+service facts, empty
- Dispatcher registration: all 3 tools route correctly
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
async def tools_db(tmp_path: Path):
    """Isolated SQLite DB with quintana-seguros + one test lead."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/lead_tools_test.db",
    )
    await db_module.init_db(settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead

        await seed_quintana(sess)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Tools Test Lead",
            phone="+5411077777",
            lead_id="test-lead-tools-001",
        )
        await sess.commit()

    yield db_module

    await db_module.close_db()


async def _insert_profile_fact(
    db_module, *, lead_id, fact_key, fact_value, superseded_at=None
):
    """Helper: insert a LeadProfileFact row."""
    from app.leads.models import LeadProfileFact

    row_id = str(uuid.uuid4())
    async with db_module.async_session_factory() as sess:
        row = LeadProfileFact(
            id=row_id,
            lead_id=lead_id,
            fact_key=fact_key,
            fact_value=fact_value,
            superseded_at=superseded_at,
        )
        sess.add(row)
        await sess.commit()
    return row_id


async def _insert_interest_history(
    db_module, *, lead_id, interest_level, recorded_at=None
):
    """Helper: insert a LeadInterestHistory row."""
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
# get_lead_profile tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_lead_profile_returns_grouped_facts(tools_db):
    """Issue #36 Phase 4: get_lead_profile returns active facts grouped by namespace.

    GIVEN a lead with active facts across profile:, pain:, signal: namespaces
    WHEN get_lead_profile(session, lead_id) is called
    THEN response contains grouped keys: profile_facts, pain_points, commitment_signals, etc.
    """
    from app.tools.get_lead_profile import get_lead_profile

    lead_id = "test-lead-tools-001"
    await _insert_profile_fact(
        tools_db, lead_id=lead_id, fact_key="profile:married", fact_value="married"
    )
    await _insert_profile_fact(
        tools_db, lead_id=lead_id, fact_key="pain:high cost", fact_value="high cost"
    )
    await _insert_profile_fact(
        tools_db,
        lead_id=lead_id,
        fact_key="signal:will call back",
        fact_value="will call back",
    )

    async with tools_db.async_session_factory() as sess:
        result = await get_lead_profile(session=sess, lead_id=lead_id)

    assert "error" not in result, f"Unexpected error: {result}"
    assert "result" in result, f"Expected 'result' key in response, got: {result}"
    text = result["result"]
    assert "married" in text, f"Expected 'married' in result text: {text!r}"
    assert "high cost" in text, f"Expected 'high cost' in result text: {text!r}"
    assert (
        "will call back" in text
    ), f"Expected 'will call back' in result text: {text!r}"


@pytest.mark.asyncio
async def test_get_lead_profile_lead_not_found(tools_db):
    """Issue #36 Phase 4: get_lead_profile returns error dict for unknown lead_id."""
    from app.tools.get_lead_profile import get_lead_profile

    async with tools_db.async_session_factory() as sess:
        result = await get_lead_profile(session=sess, lead_id="nonexistent-lead-id")

    assert result == {
        "error": "lead_not_found"
    }, f"Expected lead_not_found error, got: {result}"


@pytest.mark.asyncio
async def test_get_lead_profile_empty_facts_returns_result(tools_db):
    """Issue #36 Phase 4: get_lead_profile with no facts still returns result (not error)."""
    from app.tools.get_lead_profile import get_lead_profile

    async with tools_db.async_session_factory() as sess:
        from app.leads.service import create_lead

        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Empty Lead",
            phone="+5411088888",
            lead_id="test-lead-tools-empty",
        )
        await sess.commit()

    async with tools_db.async_session_factory() as sess:
        result = await get_lead_profile(session=sess, lead_id="test-lead-tools-empty")

    assert "error" not in result, f"Unexpected error: {result}"
    assert "result" in result


# ---------------------------------------------------------------------------
# get_lead_history tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_lead_history_returns_interest_history(tools_db):
    """Issue #36 Phase 4: get_lead_history returns interest history with up to 10 items.

    GIVEN a lead with 5 interest history rows
    WHEN get_lead_history(session, lead_id) is called
    THEN response includes interest_history with up to 10 items, newest first.
    """
    from app.tools.get_lead_history import get_lead_history

    lead_id = "test-lead-tools-001"
    now = datetime.now(timezone.utc)

    for i, level in enumerate([50, 60, 70, 80, 90]):
        await _insert_interest_history(
            tools_db,
            lead_id=lead_id,
            interest_level=level,
            recorded_at=now - timedelta(hours=5 - i),
        )

    async with tools_db.async_session_factory() as sess:
        result = await get_lead_history(session=sess, lead_id=lead_id)

    assert "error" not in result, f"Unexpected error: {result}"
    assert "result" in result
    text = result["result"]
    # Should contain interest level values
    assert (
        "90" in text
    ), f"Expected highest interest level (90) in history text: {text!r}"


@pytest.mark.asyncio
async def test_get_lead_history_empty_history(tools_db):
    """Issue #36 Phase 4: get_lead_history returns result (not error) for empty history."""
    from app.tools.get_lead_history import get_lead_history

    async with tools_db.async_session_factory() as sess:
        from app.leads.service import create_lead

        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="No History Lead",
            phone="+5411099111",
            lead_id="test-lead-no-history-tools",
        )
        await sess.commit()

    async with tools_db.async_session_factory() as sess:
        result = await get_lead_history(
            session=sess, lead_id="test-lead-no-history-tools"
        )

    assert "error" not in result, f"Unexpected error: {result}"
    assert "result" in result


@pytest.mark.asyncio
async def test_get_lead_history_lead_not_found(tools_db):
    """Issue #36 Phase 4: get_lead_history returns error dict for unknown lead_id."""
    from app.tools.get_lead_history import get_lead_history

    async with tools_db.async_session_factory() as sess:
        result = await get_lead_history(session=sess, lead_id="nonexistent-id")

    assert result == {
        "error": "lead_not_found"
    }, f"Expected lead_not_found, got: {result}"


# ---------------------------------------------------------------------------
# get_lead_pain_points tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_lead_pain_points_returns_pain_and_service_facts(tools_db):
    """Issue #36 Phase 4: get_lead_pain_points returns pain: and service_issue: facts.

    GIVEN a lead with 'pain:high premiums' and 'service_issue:claim denied' active facts
    WHEN get_lead_pain_points(session, lead_id) is called
    THEN response text contains 'high premiums' and 'claim denied'.
    """
    from app.tools.get_lead_pain_points import get_lead_pain_points

    lead_id = "test-lead-tools-001"
    await _insert_profile_fact(
        tools_db,
        lead_id=lead_id,
        fact_key="pain:high premiums",
        fact_value="high premiums",
    )
    await _insert_profile_fact(
        tools_db,
        lead_id=lead_id,
        fact_key="service_issue:claim denied",
        fact_value="claim denied",
    )

    async with tools_db.async_session_factory() as sess:
        result = await get_lead_pain_points(session=sess, lead_id=lead_id)

    assert "error" not in result, f"Unexpected error: {result}"
    assert "result" in result
    text = result["result"]
    assert "high premiums" in text, f"Expected 'high premiums' in result: {text!r}"
    assert "claim denied" in text, f"Expected 'claim denied' in result: {text!r}"


@pytest.mark.asyncio
async def test_get_lead_pain_points_empty_returns_result(tools_db):
    """Issue #36 Phase 4: get_lead_pain_points with no pain facts returns result (not error)."""
    from app.tools.get_lead_pain_points import get_lead_pain_points

    async with tools_db.async_session_factory() as sess:
        from app.leads.service import create_lead

        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="No Pain Lead",
            phone="+5411099222",
            lead_id="test-lead-no-pain",
        )
        await sess.commit()

    async with tools_db.async_session_factory() as sess:
        result = await get_lead_pain_points(session=sess, lead_id="test-lead-no-pain")

    assert "error" not in result, f"Unexpected error: {result}"
    assert "result" in result


@pytest.mark.asyncio
async def test_get_lead_pain_points_lead_not_found(tools_db):
    """Issue #36 Phase 4: get_lead_pain_points returns error dict for unknown lead_id."""
    from app.tools.get_lead_pain_points import get_lead_pain_points

    async with tools_db.async_session_factory() as sess:
        result = await get_lead_pain_points(session=sess, lead_id="nonexistent-id")

    assert result == {
        "error": "lead_not_found"
    }, f"Expected lead_not_found, got: {result}"


# ---------------------------------------------------------------------------
# Dispatcher registration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatcher_routes_get_lead_profile(tools_db):
    """Issue #36 Phase 4: dispatch_tool('get_lead_profile', ...) routes to the correct handler."""
    from app.tools.dispatcher import dispatch_tool

    lead_id = "test-lead-tools-001"

    async with tools_db.async_session_factory() as sess:
        result = await dispatch_tool(
            tool_name="get_lead_profile",
            tool_args={"lead_id": lead_id},
            client_id="quintana-seguros",
            lead_id=lead_id,
            session=sess,
        )

    # Must not return unknown_tool error
    assert "unknown_tool" not in str(
        result.get("error", "")
    ), f"Expected routing to work, got: {result}"
    assert "result" in result or "error" in result  # handler ran


@pytest.mark.asyncio
async def test_dispatcher_routes_get_lead_history(tools_db):
    """Issue #36 Phase 4: dispatch_tool('get_lead_history', ...) routes to the correct handler."""
    from app.tools.dispatcher import dispatch_tool

    lead_id = "test-lead-tools-001"

    async with tools_db.async_session_factory() as sess:
        result = await dispatch_tool(
            tool_name="get_lead_history",
            tool_args={"lead_id": lead_id},
            client_id="quintana-seguros",
            lead_id=lead_id,
            session=sess,
        )

    assert "unknown_tool" not in str(result.get("error", "")), f"Got: {result}"
    assert "result" in result or "error" in result


@pytest.mark.asyncio
async def test_dispatcher_routes_get_lead_pain_points(tools_db):
    """Issue #36 Phase 4: dispatch_tool('get_lead_pain_points', ...) routes to the correct handler."""
    from app.tools.dispatcher import dispatch_tool

    lead_id = "test-lead-tools-001"

    async with tools_db.async_session_factory() as sess:
        result = await dispatch_tool(
            tool_name="get_lead_pain_points",
            tool_args={"lead_id": lead_id},
            client_id="quintana-seguros",
            lead_id=lead_id,
            session=sess,
        )

    assert "unknown_tool" not in str(result.get("error", "")), f"Got: {result}"
    assert "result" in result or "error" in result
