"""Unit tests for capture_data tool handler.

Spec: capture_data Handler Validates and Persists
Requirements:
- Writes LeadProfileFact rows with "captured:{field}" keys
- All-or-nothing atomic write (no partial writes on missing required fields)
- Never transitions lead status
- Cross-tenant access returns lead_not_found (no leakage)
- Optional fields are skipped if not provided

Task 1.3 — RED tests written FIRST, before capture_data.py is implemented.
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
        database_url=f"sqlite+aiosqlite:///{tmp_path}/capture_data_test.db",
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


@pytest_asyncio.fixture
async def db_two_clients(tmp_path: Path):
    """DB with two clients (Quintana + another) and leads for each."""
    from app.core.config import Settings
    from app.core import database as db_module
    from app.tenants.service import create_client
    from app.leads.service import create_lead

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/capture_cross_tenant.db",
    )
    await db_module.init_db(settings)

    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import seed_leads

        await seed_quintana(sess)
        await seed_leads(sess)
        # Create a second client with a lead
        await create_client(
            sess,
            id="other-client",
            name="Other Client SA",
            agent_name="OtherAgent",
            voice_id="v-other",
        )
        await create_lead(
            sess,
            client_id="other-client",
            name="Other Lead",
            phone="+54999",
            lead_id="lead-other-001",
        )
        await sess.commit()

    yield db_module
    await db_module.close_db()


# Reusable tool_config for Quintana-like schema
_QUINTANA_TOOL_CONFIG = {
    "capture_data": {
        "type": "object",
        "properties": {
            "marca": {"type": "string"},
            "modelo": {"type": "string"},
            "anio": {"type": "integer"},
        },
        "required": ["lead_id", "marca", "modelo", "anio"],
    }
}

_OPTIONAL_FIELD_CONFIG = {
    "capture_data": {
        "type": "object",
        "properties": {
            "marca": {"type": "string"},
            "notas": {"type": "string"},
        },
        "required": ["lead_id", "marca"],
    }
}


# ---------------------------------------------------------------------------
# Scenario: Happy path — all required fields present
# Spec: AC-4, AC-5
# ---------------------------------------------------------------------------


async def test_capture_data_happy_path_writes_facts(db):
    """capture_data writes one LeadProfileFact per captured field with captured: prefix.

    GIVEN lead L1 with agent config requiring [lead_id, marca, modelo, anio]
    WHEN capture_data is called with all required fields
    THEN LeadProfileFact rows exist for captured:marca, captured:modelo, captured:anio
    AND result contains status=captured and fields list
    AND lead status is NOT changed
    """
    from app.tools.capture_data import capture_data
    from app.leads.models import LeadProfileFact
    from sqlalchemy import select

    tool_config = _QUINTANA_TOOL_CONFIG

    async with db.async_session_factory() as sess:
        result = await capture_data(
            session=sess,
            lead_id="lead-quintana-001",
            tool_config=tool_config,
            captured_fields={"marca": "Toyota", "modelo": "Corolla", "anio": 2020},
            client_id="quintana-seguros",
        )
        await sess.commit()

    # Verify return value
    assert result.get("status") == "captured"
    captured_keys = set(result.get("fields", []))
    assert captured_keys == {"marca", "modelo", "anio"}

    # Verify LeadProfileFact rows were written
    async with db.async_session_factory() as sess:
        rows = await sess.execute(
            select(LeadProfileFact).where(
                LeadProfileFact.lead_id == "lead-quintana-001",
                LeadProfileFact.superseded_at == None,  # noqa: E711
            )
        )
        facts = {r.fact_key: r.fact_value for r in rows.scalars().all()}

    assert "captured:marca" in facts
    assert facts["captured:marca"] == "Toyota"
    assert "captured:modelo" in facts
    assert facts["captured:modelo"] == "Corolla"
    assert "captured:anio" in facts
    assert facts["captured:anio"] == "2020"


async def test_capture_data_does_not_transition_lead_status(db):
    """capture_data MUST NOT change lead status. AC-5."""
    from app.tools.capture_data import capture_data
    from app.leads.service import get_lead

    tool_config = _QUINTANA_TOOL_CONFIG

    async with db.async_session_factory() as sess:
        lead_before = await get_lead(sess, "lead-quintana-001")
        initial_status = lead_before.status

    async with db.async_session_factory() as sess:
        await capture_data(
            session=sess,
            lead_id="lead-quintana-001",
            tool_config=tool_config,
            captured_fields={"marca": "Toyota", "modelo": "Corolla", "anio": 2020},
            client_id="quintana-seguros",
        )
        await sess.commit()

    async with db.async_session_factory() as sess:
        lead_after = await get_lead(sess, "lead-quintana-001")

    assert lead_after.status == initial_status, (
        f"capture_data MUST NOT change lead status. "
        f"Was {initial_status!r}, now {lead_after.status!r}"
    )


# ---------------------------------------------------------------------------
# Scenario: Missing required field → error, no DB writes (atomic)
# Spec: AC-2
# ---------------------------------------------------------------------------


async def test_capture_data_missing_required_field_returns_error(db):
    """Missing required field returns error with list of missing fields.

    GIVEN agent requiring [lead_id, marca, modelo, anio]
    WHEN capture_data is called missing modelo and anio
    THEN result = {error: missing_required_fields, missing: [modelo, anio]}
    AND no LeadProfileFact rows are written
    """
    from app.tools.capture_data import capture_data
    from app.leads.models import LeadProfileFact
    from sqlalchemy import select

    tool_config = _QUINTANA_TOOL_CONFIG

    async with db.async_session_factory() as sess:
        result = await capture_data(
            session=sess,
            lead_id="lead-quintana-001",
            tool_config=tool_config,
            captured_fields={"marca": "Toyota"},  # missing modelo and anio
            client_id="quintana-seguros",
        )
        await sess.commit()

    assert result.get("error") == "missing_required_fields"
    missing = set(result.get("missing", []))
    assert "modelo" in missing
    assert "anio" in missing

    # No facts should be written (atomicity)
    async with db.async_session_factory() as sess:
        rows = await sess.execute(
            select(LeadProfileFact).where(
                LeadProfileFact.lead_id == "lead-quintana-001",
                LeadProfileFact.fact_key.startswith("captured:"),
                LeadProfileFact.superseded_at == None,  # noqa: E711
            )
        )
        assert len(list(rows.scalars().all())) == 0, (
            "No facts should be written when required fields are missing"
        )


# ---------------------------------------------------------------------------
# Scenario: Lead not found
# Spec: AC-3 (lead_not_found response)
# ---------------------------------------------------------------------------


async def test_capture_data_lead_not_found_returns_error(db):
    """capture_data returns lead_not_found for unknown lead_id."""
    from app.tools.capture_data import capture_data

    async with db.async_session_factory() as sess:
        result = await capture_data(
            session=sess,
            lead_id="nonexistent-lead-xyz",
            tool_config=_QUINTANA_TOOL_CONFIG,
            captured_fields={"marca": "Toyota", "modelo": "Corolla", "anio": 2020},
            client_id="quintana-seguros",
        )

    assert result.get("error") == "lead_not_found"


# ---------------------------------------------------------------------------
# Scenario: Cross-tenant attempt blocked
# Spec: AC-3 (same response as not found — no leakage)
# ---------------------------------------------------------------------------


async def test_capture_data_cross_tenant_returns_lead_not_found(db_two_clients):
    """Cross-tenant lead access returns lead_not_found (no information leakage).

    GIVEN lead lead-other-001 belongs to client other-client
    WHEN capture_data is called in a session for quintana-seguros
    THEN result = {error: lead_not_found}
    """
    from app.tools.capture_data import capture_data

    async with db_two_clients.async_session_factory() as sess:
        result = await capture_data(
            session=sess,
            lead_id="lead-other-001",  # belongs to other-client
            tool_config=_QUINTANA_TOOL_CONFIG,
            captured_fields={"marca": "Toyota", "modelo": "Corolla", "anio": 2020},
            client_id="quintana-seguros",  # wrong client
        )

    assert result.get("error") == "lead_not_found", (
        "Cross-tenant access must return lead_not_found (no leakage)"
    )


# ---------------------------------------------------------------------------
# Scenario: Optional field omitted
# Spec: optional fields not in "required" are not written
# ---------------------------------------------------------------------------


async def test_capture_data_optional_field_omitted_is_not_written(db):
    """Optional field omitted from call → no fact written for that field.

    GIVEN agent config with notas as optional (not in required)
    WHEN capture_data is called without notas
    THEN only captured:marca fact is written; no captured:notas fact
    """
    from app.tools.capture_data import capture_data
    from app.leads.models import LeadProfileFact
    from sqlalchemy import select

    async with db.async_session_factory() as sess:
        result = await capture_data(
            session=sess,
            lead_id="lead-quintana-001",
            tool_config=_OPTIONAL_FIELD_CONFIG,
            captured_fields={"marca": "Toyota"},  # notas is optional, not provided
            client_id="quintana-seguros",
        )
        await sess.commit()

    assert result.get("status") == "captured"
    assert "marca" in result.get("fields", [])
    assert "notas" not in result.get("fields", [])

    async with db.async_session_factory() as sess:
        notas_rows = await sess.execute(
            select(LeadProfileFact).where(
                LeadProfileFact.lead_id == "lead-quintana-001",
                LeadProfileFact.fact_key == "captured:notas",
                LeadProfileFact.superseded_at == None,  # noqa: E711
            )
        )
        assert len(list(notas_rows.scalars().all())) == 0, (
            "Optional field omitted must not produce a fact row"
        )


# ---------------------------------------------------------------------------
# Scenario: Atomic upsert — second write supersedes first
# Spec: LeadProfileFact append-and-supersede pattern
# ---------------------------------------------------------------------------


async def test_capture_data_second_write_supersedes_first(db):
    """Second capture_data call for same field supersedes the first.

    GIVEN a fact captured:marca=Toyota already exists
    WHEN capture_data is called again with marca=Honda
    THEN only one active (superseded_at=NULL) row for captured:marca exists
    AND its value is Honda
    """
    from app.tools.capture_data import capture_data
    from app.leads.models import LeadProfileFact
    from sqlalchemy import select

    # First write
    async with db.async_session_factory() as sess:
        await capture_data(
            session=sess,
            lead_id="lead-quintana-001",
            tool_config=_QUINTANA_TOOL_CONFIG,
            captured_fields={"marca": "Toyota", "modelo": "Corolla", "anio": 2020},
            client_id="quintana-seguros",
        )
        await sess.commit()

    # Second write — different value for marca
    async with db.async_session_factory() as sess:
        result = await capture_data(
            session=sess,
            lead_id="lead-quintana-001",
            tool_config=_QUINTANA_TOOL_CONFIG,
            captured_fields={"marca": "Honda", "modelo": "Civic", "anio": 2021},
            client_id="quintana-seguros",
        )
        await sess.commit()

    assert result.get("status") == "captured"

    # Only one active fact for captured:marca
    async with db.async_session_factory() as sess:
        rows = await sess.execute(
            select(LeadProfileFact).where(
                LeadProfileFact.lead_id == "lead-quintana-001",
                LeadProfileFact.fact_key == "captured:marca",
                LeadProfileFact.superseded_at == None,  # noqa: E711
            )
        )
        active_marca = list(rows.scalars().all())

    assert len(active_marca) == 1, "Only one active fact for captured:marca"
    assert active_marca[0].fact_value == "Honda", (
        f"Expected Honda (second write), got {active_marca[0].fact_value!r}"
    )
