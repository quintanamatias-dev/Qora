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
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations
    await _init_db_with_migrations(db_module, settings)

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
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations
    await _init_db_with_migrations(db_module, settings)

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


# ---------------------------------------------------------------------------
# WU-5 Task 5.1 — Dynamic capture_data schema + lead_custom_fields writes
#
# Spec: dynamic-lead-fields — Requirement: capture_data Writes to lead_custom_fields
# AC-5: capture_data schema contains exactly the fields from field_definitions
#
# RED tests: these define the NEW behavior.
# Existing tests above (LeadProfileFact writes) document backward-compat behavior.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Scenario CD-6: capture_data writes to lead_custom_fields (new primary storage)
# Spec: "capture_data MUST upsert each captured field to lead_custom_fields"
# ---------------------------------------------------------------------------


async def test_capture_data_writes_to_lead_custom_fields(db):
    """capture_data upserts business fields to lead_custom_fields table.

    GIVEN live call for lead L1, client quintana-seguros
    WHEN capture_data(lead_id="lead-quintana-001", car_make="Toyota", car_year=2022) is called
    THEN lead_custom_fields rows are upserted for car_make and car_year
    AND result contains status=captured with field names
    """
    from app.tools.capture_data import capture_data
    from app.leads.models import LeadCustomField
    from sqlalchemy import select

    tool_config = {
        "capture_data": {
            "type": "object",
            "properties": {
                "car_make": {"type": "string"},
                "car_year": {"type": "integer"},
            },
            "required": ["lead_id", "car_make", "car_year"],
        }
    }

    # Provide field_type_map so handler knows how to coerce values
    field_type_map = {"car_make": "string", "car_year": "integer"}

    async with db.async_session_factory() as sess:
        result = await capture_data(
            session=sess,
            lead_id="lead-quintana-001",
            tool_config=tool_config,
            captured_fields={"car_make": "Toyota", "car_year": 2022},
            client_id="quintana-seguros",
            field_type_map=field_type_map,
        )
        await sess.commit()

    assert result.get("status") == "captured", f"Expected captured, got: {result}"
    assert set(result.get("fields", [])) == {"car_make", "car_year"}

    # Verify rows in lead_custom_fields
    async with db.async_session_factory() as sess:
        rows = await sess.execute(
            select(LeadCustomField).where(
                LeadCustomField.lead_id == "lead-quintana-001",
                LeadCustomField.client_id == "quintana-seguros",
            )
        )
        cf_rows = {r.field_key: r.field_value for r in rows.scalars().all()}

    assert "car_make" in cf_rows, f"car_make must be in lead_custom_fields, got: {cf_rows}"
    assert cf_rows["car_make"] == "Toyota"
    assert "car_year" in cf_rows, f"car_year must be in lead_custom_fields, got: {cf_rows}"
    assert cf_rows["car_year"] == "2022"  # stored as TEXT


# ---------------------------------------------------------------------------
# Scenario CD-7: capture_data dual-writes to LeadProfileFact for backward compat
# Spec: "MUST also continue writing LeadProfileFact row under captured:{field_name}"
# ---------------------------------------------------------------------------


async def test_capture_data_dual_writes_lead_profile_fact(db):
    """capture_data continues writing captured: LeadProfileFact rows for backward compat.

    GIVEN capture_data writes car_make to lead_custom_fields
    THEN a LeadProfileFact row captured:car_make ALSO exists
    (dual-write for intelligence pipeline backward compat during WU-5)
    """
    from app.tools.capture_data import capture_data
    from app.leads.models import LeadProfileFact
    from sqlalchemy import select

    tool_config = {
        "capture_data": {
            "type": "object",
            "properties": {
                "car_make": {"type": "string"},
            },
            "required": ["lead_id", "car_make"],
        }
    }
    field_type_map = {"car_make": "string"}

    async with db.async_session_factory() as sess:
        result = await capture_data(
            session=sess,
            lead_id="lead-quintana-001",
            tool_config=tool_config,
            captured_fields={"car_make": "Ford"},
            client_id="quintana-seguros",
            field_type_map=field_type_map,
        )
        await sess.commit()

    assert result.get("status") == "captured"

    # LeadProfileFact backward-compat row must also exist
    async with db.async_session_factory() as sess:
        rows = await sess.execute(
            select(LeadProfileFact).where(
                LeadProfileFact.lead_id == "lead-quintana-001",
                LeadProfileFact.fact_key == "captured:car_make",
                LeadProfileFact.superseded_at == None,  # noqa: E711
            )
        )
        facts = list(rows.scalars().all())

    assert len(facts) == 1, (
        "capture_data must dual-write a captured:car_make LeadProfileFact row "
        f"for backward compat. Rows found: {facts}"
    )
    assert facts[0].fact_value == "Ford"


# ---------------------------------------------------------------------------
# Scenario CD-8: capture_data without field_type_map uses "string" default
# Spec: field_type_map is optional; missing type defaults to "string" coercion
# ---------------------------------------------------------------------------


async def test_capture_data_no_field_type_map_uses_string_default(db):
    """capture_data without field_type_map defaults to string for all fields.

    GIVEN capture_data called without field_type_map kwarg
    WHEN business field car_make is captured
    THEN lead_custom_fields row for car_make is written with field_type="string"
    """
    from app.tools.capture_data import capture_data
    from app.leads.models import LeadCustomField
    from sqlalchemy import select

    tool_config = {
        "capture_data": {
            "type": "object",
            "properties": {
                "car_make": {"type": "string"},
            },
            "required": ["lead_id", "car_make"],
        }
    }

    async with db.async_session_factory() as sess:
        result = await capture_data(
            session=sess,
            lead_id="lead-quintana-001",
            tool_config=tool_config,
            captured_fields={"car_make": "Volkswagen"},
            client_id="quintana-seguros",
            # No field_type_map — defaults to string
        )
        await sess.commit()

    assert result.get("status") == "captured"

    async with db.async_session_factory() as sess:
        rows = await sess.execute(
            select(LeadCustomField).where(
                LeadCustomField.lead_id == "lead-quintana-001",
                LeadCustomField.field_key == "car_make",
            )
        )
        cf = rows.scalar_one_or_none()

    assert cf is not None, "lead_custom_fields row must be created even without field_type_map"
    assert cf.field_type == "string"
    assert cf.field_value == "Volkswagen"


# ---------------------------------------------------------------------------
# Scenario CD-9: Post-call facts pipeline is unaffected — no captured: facts
#                from post-call analysis; only from direct capture_data calls
# Spec: "Post-call profile_facts pipeline remains completely separate and unaffected"
# ---------------------------------------------------------------------------


def test_post_call_pipeline_has_no_capture_data_dependency():
    """The summarizer/profile_facts pipeline imports do not depend on capture_data tool.

    This is a static import test — confirms the separation between:
    - Live call tool: capture_data (writes real-time business data)
    - Post-call pipeline: summarizer → profile_facts (separate analysis flow)

    If this test fails, it means we accidentally introduced a cross-dependency.
    """
    import importlib
    import sys

    # Import summarizer — must succeed without importing capture_data
    summarizer_module = importlib.import_module("app.summarizer")
    assert summarizer_module is not None

    # Confirm capture_data module is NOT imported by summarizer (no cross-dependency)
    # The summarizer should not have capture_data in its dependency chain
    summarizer_file = getattr(summarizer_module, "__file__", "") or ""
    # Read source to check for direct import
    if summarizer_file:
        import pathlib
        source = pathlib.Path(summarizer_file).read_text()
        assert "from app.tools.capture_data" not in source, (
            "summarizer must NOT import capture_data tool — pipelines must stay separate"
        )
        assert "import capture_data" not in source, (
            "summarizer must NOT import capture_data tool — pipelines must stay separate"
        )


# ---------------------------------------------------------------------------
# Scenario CD-10: build_capture_data_definition from CRMConfig field_definitions
# Spec: AC-5 — capture_data schema contains exactly the fields from field_definitions
# Spec: "Each entry in field_definitions MUST produce one property in the schema"
# ---------------------------------------------------------------------------


def test_build_capture_data_from_field_definitions_produces_correct_schema():
    """build_capture_data_from_field_definitions generates schema from CRMConfig.custom_fields.

    GIVEN field_definitions lists car_make (string), car_year (integer), age (integer)
    WHEN build_capture_data_from_field_definitions(crm_config) is called
    THEN the schema properties contain exactly car_make, car_year, age with correct JSON types
    AND lead_id is always included as a required property regardless of config
    """
    from app.tools.registry import build_capture_data_from_field_definitions
    from app.integrations.crm_config import CRMConfig, CustomFieldDef

    crm_config = CRMConfig(
        provider="airtable",
        base_id="app123",
        table_id="tbl123",
        api_key="LITERAL_KEY",
        match_field="lead_id",
        custom_fields=[
            CustomFieldDef(field_key="car_make", field_type="string", label="Car Make"),
            CustomFieldDef(field_key="car_year", field_type="integer", label="Car Year"),
            CustomFieldDef(field_key="age", field_type="integer", label="Age"),
        ],
    )

    result = build_capture_data_from_field_definitions(crm_config)

    assert result is not None, "build_capture_data_from_field_definitions must return a schema"
    func = result["function"]
    assert func["name"] == "capture_data"

    params = func["parameters"]
    props = params["properties"]
    required = params["required"]

    # Each field_definition must produce one property
    assert "car_make" in props, "car_make must be in properties"
    assert "car_year" in props, "car_year must be in properties"
    assert "age" in props, "age must be in properties"

    # JSON type mapping: string→string, integer→integer
    assert props["car_make"]["type"] == "string"
    assert props["car_year"]["type"] == "integer"
    assert props["age"]["type"] == "integer"

    # lead_id always present (required for handler lookup)
    assert "lead_id" in props, "lead_id must always be in properties"
    assert "lead_id" in required, "lead_id must always be in required"


def test_build_capture_data_from_field_definitions_no_custom_fields_returns_none():
    """build_capture_data_from_field_definitions returns None when no field_definitions.

    GIVEN a client config has no field_definitions (custom_fields=[])
    WHEN build_capture_data_from_field_definitions is called for this client
    THEN None is returned → capture_data excluded from tool list
    """
    from app.tools.registry import build_capture_data_from_field_definitions
    from app.integrations.crm_config import CRMConfig

    crm_config = CRMConfig(
        provider="airtable",
        base_id="app123",
        table_id="tbl123",
        api_key="LITERAL_KEY",
        match_field="lead_id",
        custom_fields=[],  # no field_definitions
    )

    result = build_capture_data_from_field_definitions(crm_config)
    assert result is None, (
        "build_capture_data_from_field_definitions must return None when no custom_fields"
    )


def test_build_capture_data_from_field_definitions_label_used_as_description():
    """Field label is used as property description in the generated schema.

    GIVEN field_definition with label="Car Make"
    WHEN schema is built
    THEN properties["car_make"]["description"] contains "Car Make" or similar
    """
    from app.tools.registry import build_capture_data_from_field_definitions
    from app.integrations.crm_config import CRMConfig, CustomFieldDef

    crm_config = CRMConfig(
        provider="airtable",
        base_id="app123",
        table_id="tbl123",
        api_key="LITERAL_KEY",
        match_field="lead_id",
        custom_fields=[
            CustomFieldDef(field_key="car_make", field_type="string", label="Car Make"),
        ],
    )

    result = build_capture_data_from_field_definitions(crm_config)
    assert result is not None
    props = result["function"]["parameters"]["properties"]
    car_make_prop = props["car_make"]
    # Label should appear as description or title
    assert "description" in car_make_prop or "title" in car_make_prop, (
        "field label must be reflected in the property schema"
    )


def test_required_custom_fields_not_in_tool_schema_required():
    """crm.yaml required:true fields must NOT become required tool parameters.

    P1 fix (partial capture): CustomFieldDef.required marks fields for quote-ready
    evaluation only. If they leak into the tool schema's required list, the model
    cannot emit a valid capture_data call until the lead provides ALL of them —
    so partial data captured mid-call is never persisted.

    GIVEN field_definitions where age and zona have required=true
    WHEN build_capture_data_from_field_definitions is called
    THEN the schema required list contains ONLY lead_id
    AND age/zona remain present as optional properties with type/description intact
    """
    from app.tools.registry import build_capture_data_from_field_definitions
    from app.integrations.crm_config import CRMConfig, CustomFieldDef

    crm_config = CRMConfig(
        provider="airtable",
        base_id="app123",
        table_id="tbl123",
        api_key="LITERAL_KEY",
        match_field="lead_id",
        custom_fields=[
            CustomFieldDef(field_key="age", field_type="integer", label="Age", required=True),
            CustomFieldDef(field_key="zona", field_type="string", label="Zone", required=True),
            CustomFieldDef(
                field_key="current_insurance",
                field_type="string",
                label="Current Insurance",
                required=False,
            ),
        ],
    )

    result = build_capture_data_from_field_definitions(crm_config)
    assert result is not None
    params = result["function"]["parameters"]

    assert params["required"] == ["lead_id"], (
        "Only lead_id may be required in the tool schema; "
        f"got: {params['required']}"
    )

    # Properties and metadata must be preserved so the model can still capture them
    props = params["properties"]
    assert props["age"] == {"type": "integer", "description": "Age"}
    assert props["zona"] == {"type": "string", "description": "Zone"}
    assert props["current_insurance"] == {
        "type": "string",
        "description": "Current Insurance",
    }


# ---------------------------------------------------------------------------
# Scenario CD-11: _QUINTANA_TOOL_CONFIG removed from tenants/service.py
# Spec: "_QUINTANA_TOOL_CONFIG constant MUST be removed"
# AC-5: Schema always comes from field_definitions, never from a hardcoded constant
# ---------------------------------------------------------------------------


def test_quintana_tool_config_constant_removed_from_service():
    """_QUINTANA_TOOL_CONFIG must not exist as a module-level constant in tenants/service.py.

    Spec AC-5: 'The _QUINTANA_TOOL_CONFIG constant MUST be removed.'
    The schema is now built dynamically from crm.yaml field_definitions.
    """
    import app.tenants.service as service_module

    assert not hasattr(service_module, "_QUINTANA_TOOL_CONFIG"), (
        "_QUINTANA_TOOL_CONFIG must be removed from tenants/service.py. "
        "Schema is now generated dynamically from CRMConfig.custom_fields."
    )


def test_register_interest_module_does_not_exist():
    """register_interest.py module must not exist — tool was removed.

    Spec AC-6: 'register_interest absent from codebase and tool registry'
    """
    import importlib
    import importlib.util

    spec = importlib.util.find_spec("app.tools.register_interest")
    assert spec is None, (
        "app.tools.register_interest module must be deleted. "
        "It was superseded by capture_data in WU-5."
    )


# ---------------------------------------------------------------------------
# Scenario CD-12: capture_data partial-write atomicity
# Judgment Day Round 2 — confirmed by both judges
# Problem: if first field succeeds and second fails coercion, no writes at all
# ---------------------------------------------------------------------------


async def test_capture_data_failed_coercion_writes_zero_custom_fields(db):
    """capture_data with a bad coercion value must write ZERO custom fields.

    GIVEN a fresh lead with no existing custom fields
    AND a tool_config with car_make (string) and car_year (integer)
    AND captured_fields has car_make="Toyota" (valid) and car_year="abc" (invalid int)
    WHEN capture_data is called
    THEN result has error=custom_field_write_failed
    AND no lead_custom_fields rows exist (no partial write — car_make NOT written)
    """
    from app.tools.capture_data import capture_data
    from app.leads.models import LeadCustomField
    from app.leads.service import create_lead
    from sqlalchemy import select

    # Use a fresh lead with no pre-seeded custom fields to avoid fixture interference
    async with db.async_session_factory() as sess:
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Atomicity Test Lead",
            phone="+54911000001",
            lead_id="lead-atomicity-test-001",
        )
        await sess.commit()

    tool_config = {
        "capture_data": {
            "type": "object",
            "properties": {
                "car_make": {"type": "string"},
                "car_year": {"type": "integer"},
            },
            "required": ["lead_id", "car_make", "car_year"],
        }
    }
    field_type_map = {"car_make": "string", "car_year": "integer"}

    async with db.async_session_factory() as sess:
        result = await capture_data(
            session=sess,
            lead_id="lead-atomicity-test-001",
            tool_config=tool_config,
            captured_fields={"car_make": "Toyota", "car_year": "abc"},  # abc is invalid int
            client_id="quintana-seguros",
            field_type_map=field_type_map,
        )
        await sess.commit()

    # Must report error
    assert result.get("error") == "custom_field_write_failed", (
        f"Expected custom_field_write_failed, got: {result}"
    )

    # No custom fields must have been written — atomicity enforced
    async with db.async_session_factory() as sess:
        rows = await sess.execute(
            select(LeadCustomField).where(
                LeadCustomField.lead_id == "lead-atomicity-test-001",
                LeadCustomField.client_id == "quintana-seguros",
            )
        )
        cf_rows = list(rows.scalars().all())

    assert len(cf_rows) == 0, (
        f"Expected zero custom_fields on coercion failure (car_make must NOT be written), "
        f"found {len(cf_rows)}: " + str([r.field_key for r in cf_rows])
    )


async def test_capture_data_failed_coercion_first_field_writes_zero(db):
    """capture_data fails on first-field coercion error — writes nothing.

    GIVEN a fresh lead with no existing custom fields
    AND car_year is declared integer but value "NotANumber" is invalid
    WHEN capture_data is called
    THEN no custom_fields row is written (not even car_make which follows)
    """
    from app.tools.capture_data import capture_data
    from app.leads.models import LeadCustomField
    from app.leads.service import create_lead
    from sqlalchemy import select

    # Use a fresh lead with no pre-seeded custom fields
    async with db.async_session_factory() as sess:
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Atomicity Test Lead 2",
            phone="+54911000002",
            lead_id="lead-atomicity-test-002",
        )
        await sess.commit()

    tool_config = {
        "capture_data": {
            "type": "object",
            "properties": {
                "car_year": {"type": "integer"},
                "car_make": {"type": "string"},
            },
            "required": ["lead_id", "car_year", "car_make"],
        }
    }
    # car_year fails coercion; car_make is valid but must NOT be written
    field_type_map = {"car_year": "integer", "car_make": "string"}

    async with db.async_session_factory() as sess:
        result = await capture_data(
            session=sess,
            lead_id="lead-atomicity-test-002",
            tool_config=tool_config,
            captured_fields={"car_year": "NotANumber", "car_make": "Honda"},
            client_id="quintana-seguros",
            field_type_map=field_type_map,
        )
        await sess.commit()

    assert result.get("error") == "custom_field_write_failed"

    async with db.async_session_factory() as sess:
        rows = await sess.execute(
            select(LeadCustomField).where(
                LeadCustomField.lead_id == "lead-atomicity-test-002",
                LeadCustomField.client_id == "quintana-seguros",
            )
        )
        cf_rows = list(rows.scalars().all())

    assert len(cf_rows) == 0, (
        "No custom fields must be written when any field fails coercion. "
        f"Found: {[r.field_key for r in cf_rows]}"
    )
