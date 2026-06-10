"""Unit tests for tools dispatcher.

RED: References app.tools.dispatcher which is not yet implemented.
Covers: tool routing, error handling for unknown tools.
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


async def test_dispatcher_mark_not_interested_now_returns_tool_removed(db):
    """Phase 2: mark_not_interested removed — dispatch returns tool_removed error.

    Previously tested that it routed to the handler. Phase 2 removes the legacy tool
    so old agents that still call it get a tool_removed response (no crash).
    """
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

    assert result.get("error") == "tool_removed", (
        f"mark_not_interested must return tool_removed post-Phase2, got: {result}"
    )


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


# ---------------------------------------------------------------------------
# Round 2 fix: dispatcher must pass client_id to schedule_followup
# Issue 1 — TZ fix incomplete in dispatcher path
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_with_scheduler(tmp_path: Path):
    """DB with quintana (scheduler_enabled=True, America/New_York tz) + test leads."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/dispatcher_sched_test.db",
    )
    await db_module.init_db(settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import seed_leads

        await seed_quintana(sess)
        await seed_leads(sess)
        await sess.commit()

    # Enable scheduler and set timezone to New York (UTC-5 in winter)
    async with db_module.async_session_factory() as sess:
        from app.tenants.models import Client

        client = await sess.get(Client, "quintana-seguros")
        client.scheduler_enabled = True
        client.scheduler_timezone = "America/New_York"
        await sess.commit()

    yield db_module
    await db_module.close_db()


async def test_dispatcher_schedule_followup_removed_returns_tool_removed(db_with_scheduler):
    """Phase 2: schedule_followup removed — dispatch returns tool_removed (no crash).

    Previously tested TZ pass-through for schedule_followup. Now that the tool is
    removed in Phase 2, verify that calling it returns a structured tool_removed error
    instead of routing to the handler. The SSE stream receives the error gracefully.
    """
    from app.tools.dispatcher import dispatch_tool

    async with db_with_scheduler.async_session_factory() as sess:
        result = await dispatch_tool(
            tool_name="schedule_followup",
            tool_args={
                "lead_id": "lead-quintana-003",
                "followup_date": "2026-06-01T11:00",
            },
            client_id="quintana-seguros",
            lead_id="lead-quintana-003",
            session=sess,
        )

    assert result.get("error") == "tool_removed", (
        f"schedule_followup must return tool_removed post-Phase2, got: {result}"
    )
    assert "detail" in result


# ---------------------------------------------------------------------------
# Task 1.5 — capture_data dispatch with agent_tool_config injection
# Spec: Dispatcher Injects Agent Config into capture_data Calls
# ---------------------------------------------------------------------------


async def test_dispatcher_routes_capture_data_with_agent_tool_config(db):
    """dispatch_tool routes 'capture_data' and passes agent_tool_config to handler.

    GIVEN dispatch_tool called with capture_data and valid agent_tool_config
    WHEN agent tool config has capture_data schema
    THEN result contains status=captured
    AND no error is returned
    """
    from app.tools.dispatcher import dispatch_tool
    from app.leads.models import LeadProfileFact
    from sqlalchemy import select

    tool_config = {
        "capture_data": {
            "type": "object",
            "properties": {
                "marca": {"type": "string"},
                "modelo": {"type": "string"},
            },
            "required": ["lead_id", "marca", "modelo"],
        }
    }

    async with db.async_session_factory() as sess:
        result = await dispatch_tool(
            tool_name="capture_data",
            tool_args={
                "lead_id": "lead-quintana-001",
                "marca": "Toyota",
                "modelo": "Corolla",
            },
            client_id="quintana-seguros",
            lead_id="lead-quintana-001",
            session=sess,
            agent_tool_config=tool_config,
        )
        await sess.commit()

    assert "error" not in result, f"Expected success, got: {result}"
    assert result.get("status") == "captured"
    assert "marca" in result.get("fields", [])

    # Verify DB write
    async with db.async_session_factory() as sess:
        rows = await sess.execute(
            select(LeadProfileFact).where(
                LeadProfileFact.lead_id == "lead-quintana-001",
                LeadProfileFact.fact_key == "captured:marca",
                LeadProfileFact.superseded_at == None,  # noqa: E711
            )
        )
        facts = list(rows.scalars().all())
    assert len(facts) == 1
    assert facts[0].fact_value == "Toyota"


async def test_dispatcher_capture_data_partial_capture_with_required_crm_fields(db):
    """Partial capture is accepted when crm.yaml marks fields as required.

    P1 fix (partial capture): required:true in crm.yaml is for quote-ready
    evaluation, not tool-call validation. Capturing ONE field mid-call must
    succeed and persist, even when other crm.yaml fields are required=true.

    GIVEN crm_config with car_make/age/zona where age+zona are required=true
    WHEN dispatch_tool('capture_data') is called with ONLY car_make
    THEN the capture succeeds and car_make is written to lead_custom_fields
    """
    from app.tools.dispatcher import dispatch_tool
    from app.integrations.crm_config import CRMConfig, CustomFieldDef
    from app.leads import lead_custom_fields_service

    crm_config = CRMConfig(
        provider="airtable",
        base_id="app123",
        table_id="tbl123",
        api_key="LITERAL_KEY",
        match_field="lead_id",
        custom_fields=[
            CustomFieldDef(field_key="car_make", field_type="string", label="Car Make", required=True),
            CustomFieldDef(field_key="age", field_type="integer", label="Age", required=True),
            CustomFieldDef(field_key="zona", field_type="string", label="Zone", required=True),
        ],
    )

    async with db.async_session_factory() as sess:
        result = await dispatch_tool(
            tool_name="capture_data",
            tool_args={"lead_id": "lead-quintana-001", "car_make": "Toyota"},
            client_id="quintana-seguros",
            lead_id="lead-quintana-001",
            session=sess,
            crm_config=crm_config,
        )
        await sess.commit()

    assert result.get("status") == "captured", (
        f"Partial capture of one field must succeed, got: {result}"
    )
    assert result.get("fields") == ["car_make"]

    # Verify the partial field was written to lead_custom_fields
    async with db.async_session_factory() as sess:
        stored = await lead_custom_fields_service.get_all(
            sess, "lead-quintana-001", "quintana-seguros"
        )
    assert stored.get("car_make") == "Toyota"


async def test_dispatcher_capture_data_without_tool_config_returns_error(db):
    """dispatch_tool with capture_data and no agent_tool_config returns error.

    GIVEN dispatch_tool called with capture_data but agent_tool_config=None
    WHEN called
    THEN result contains an error (missing_tool_config or similar)
    AND no exception is raised
    """
    from app.tools.dispatcher import dispatch_tool

    async with db.async_session_factory() as sess:
        result = await dispatch_tool(
            tool_name="capture_data",
            tool_args={"lead_id": "lead-quintana-001", "marca": "Toyota"},
            client_id="quintana-seguros",
            lead_id="lead-quintana-001",
            session=sess,
            agent_tool_config=None,
        )

    assert "error" in result, f"Expected error, got: {result}"


# ---------------------------------------------------------------------------
# Task 2.3 RED: Legacy tools removed — return tool_removed error
# Spec: Legacy Tool Modules Removed from Dispatch Registry
# ---------------------------------------------------------------------------


async def test_dispatcher_register_interest_returns_tool_removed(db):
    """Phase 2: dispatch_tool('register_interest') returns tool_removed error.

    GIVEN Phase 2 is complete and legacy tools removed from _TOOL_REGISTRY
    WHEN dispatch_tool('register_interest', ...) is called
    THEN result is {'error': 'tool_removed', 'detail': ...}
    AND no exception is raised
    """
    from app.tools.dispatcher import dispatch_tool

    async with db.async_session_factory() as sess:
        result = await dispatch_tool(
            tool_name="register_interest",
            tool_args={
                "lead_id": "lead-quintana-001",
                "car_make": "Toyota",
                "car_model": "Corolla",
            },
            client_id="quintana-seguros",
            lead_id="lead-quintana-001",
            session=sess,
        )

    assert result.get("error") == "tool_removed", (
        f"register_interest must return tool_removed, got: {result}"
    )
    assert "detail" in result


async def test_dispatcher_mark_not_interested_returns_tool_removed(db):
    """Phase 2: dispatch_tool('mark_not_interested') returns tool_removed error.

    GIVEN mark_not_interested removed from _TOOL_REGISTRY
    WHEN dispatch_tool('mark_not_interested', ...) is called
    THEN result is {'error': 'tool_removed', 'detail': ...}
    """
    from app.tools.dispatcher import dispatch_tool

    async with db.async_session_factory() as sess:
        result = await dispatch_tool(
            tool_name="mark_not_interested",
            tool_args={"lead_id": "lead-quintana-003", "reason": "No interest"},
            client_id="quintana-seguros",
            lead_id="lead-quintana-003",
            session=sess,
        )

    assert result.get("error") == "tool_removed", (
        f"mark_not_interested must return tool_removed, got: {result}"
    )
    assert "detail" in result


async def test_dispatcher_schedule_followup_returns_tool_removed(db):
    """Phase 2: dispatch_tool('schedule_followup') returns tool_removed error.

    GIVEN schedule_followup removed from _TOOL_REGISTRY
    WHEN dispatch_tool('schedule_followup', ...) is called
    THEN result is {'error': 'tool_removed', 'detail': ...}
    """
    from app.tools.dispatcher import dispatch_tool

    async with db.async_session_factory() as sess:
        result = await dispatch_tool(
            tool_name="schedule_followup",
            tool_args={"lead_id": "lead-quintana-001", "followup_date": "2026-07-01"},
            client_id="quintana-seguros",
            lead_id="lead-quintana-001",
            session=sess,
        )

    assert result.get("error") == "tool_removed", (
        f"schedule_followup must return tool_removed, got: {result}"
    )
    assert "detail" in result


def test_registry_does_not_contain_legacy_tools():
    """Phase 2: TOOL_DEFINITIONS must NOT contain register_interest, mark_not_interested,
    or schedule_followup.

    Spec: _TOOL_REGISTRY MUST NOT contain the three legacy tools post-Phase 2.
    """
    from app.tools.registry import TOOL_DEFINITIONS

    assert "register_interest" not in TOOL_DEFINITIONS, (
        "register_interest must be removed from TOOL_DEFINITIONS in Phase 2"
    )
    assert "mark_not_interested" not in TOOL_DEFINITIONS, (
        "mark_not_interested must be removed from TOOL_DEFINITIONS in Phase 2"
    )
    assert "schedule_followup" not in TOOL_DEFINITIONS, (
        "schedule_followup must be removed from TOOL_DEFINITIONS in Phase 2"
    )
