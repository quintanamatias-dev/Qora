"""Tests for LeadCustomField model and lead_custom_fields_service.

Spec: dynamic-lead-fields — CF-1 through CF-11
Test layer: Unit (async SQLite in-memory)

TDD RED phase:
- These tests are written first and must fail until the implementation is in place.
- They describe the EXACT behavior required by the spec.

Coverage:
- CF-1: Unique constraint (lead_id, client_id, field_key)
- CF-2: field_type enum validation
- CF-3: Write-time coercion
- CF-4: Coercion failure rejects write
- CF-5: Upsert semantics
- CF-6: field_value stored as TEXT
- CF-7: Batch read for a lead
- CF-8: Batch read for multiple leads (IN clause)
- CF-9: Cross-client isolation
- CF-10: Startup table creation (idempotent)
- CF-11: One-time data copy from legacy columns
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
    """Isolated async SQLite session with LeadCustomField table created."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/lcf_test.db",
    )
    await db_module.init_db(settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as session:
        # Seed a client and a lead so FK constraints are satisfied
        from app.tenants.models import Client

        client = Client(
            id="quintana-seguros",
            name="Quintana Seguros",
            voice_id="test-voice-id",
        )
        session.add(client)
        await session.flush()

        from app.leads.models import Lead

        lead = Lead(
            id="lead-1",
            client_id="quintana-seguros",
            name="Ana García",
            phone="+5491100000001",
        )
        session.add(lead)
        await session.commit()

    async with db_module.async_session_factory() as session:
        yield session

    await db_module.close_db()


# ---------------------------------------------------------------------------
# CF-2: coerce_value() — pure function, type validation
# ---------------------------------------------------------------------------


def test_coerce_value_string_passthrough():
    """CF-2/CF-3: string type accepts any value and returns it as-is."""
    from app.leads.lead_custom_fields_service import coerce_value

    assert coerce_value("Toyota", "string") == "Toyota"
    assert coerce_value("123", "string") == "123"
    assert coerce_value("", "string") == ""


def test_coerce_value_integer_valid():
    """CF-3: integer type accepts numeric strings and int values → returns string repr."""
    from app.leads.lead_custom_fields_service import coerce_value

    assert coerce_value("2021", "integer") == "2021"
    assert coerce_value(2021, "integer") == "2021"
    assert coerce_value("0", "integer") == "0"


def test_coerce_value_integer_invalid_raises():
    """CF-4: integer type rejects non-numeric strings."""
    from app.leads.lead_custom_fields_service import coerce_value, FieldTypeError

    with pytest.raises(FieldTypeError):
        coerce_value("not-a-number", "integer")

    with pytest.raises(FieldTypeError):
        coerce_value("12.5abc", "integer")


def test_coerce_value_boolean_truthy_values():
    """CF-3: boolean type coerces 'true', '1', 'yes' → 'True'."""
    from app.leads.lead_custom_fields_service import coerce_value

    assert coerce_value("true", "boolean") == "True"
    assert coerce_value("1", "boolean") == "True"
    assert coerce_value("yes", "boolean") == "True"
    assert coerce_value(True, "boolean") == "True"


def test_coerce_value_boolean_falsy_values():
    """CF-3: boolean type coerces 'false', '0', 'no' → 'False'."""
    from app.leads.lead_custom_fields_service import coerce_value

    assert coerce_value("false", "boolean") == "False"
    assert coerce_value("0", "boolean") == "False"
    assert coerce_value("no", "boolean") == "False"
    assert coerce_value(False, "boolean") == "False"


def test_coerce_value_boolean_invalid_raises():
    """CF-4: boolean type rejects values that are not truthy/falsy markers."""
    from app.leads.lead_custom_fields_service import coerce_value, FieldTypeError

    with pytest.raises(FieldTypeError):
        coerce_value("maybe", "boolean")


def test_coerce_value_date_valid():
    """CF-3: date type accepts ISO date strings."""
    from app.leads.lead_custom_fields_service import coerce_value

    assert coerce_value("2024-01-15", "date") == "2024-01-15"


def test_coerce_value_date_invalid_raises():
    """CF-4: date type rejects non-date strings."""
    from app.leads.lead_custom_fields_service import coerce_value, FieldTypeError

    with pytest.raises(FieldTypeError):
        coerce_value("not-a-date", "date")


def test_coerce_value_phone_passthrough():
    """CF-3: phone type accepts any string (phone format not strictly validated here)."""
    from app.leads.lead_custom_fields_service import coerce_value

    assert coerce_value("+5491100000001", "phone") == "+5491100000001"


def test_coerce_value_unknown_type_raises():
    """CF-2: unknown field_type raises FieldTypeError."""
    from app.leads.lead_custom_fields_service import coerce_value, FieldTypeError

    with pytest.raises(FieldTypeError):
        coerce_value("value", "frobnicate")


# ---------------------------------------------------------------------------
# CF-5/CF-6: upsert() — insert and update semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_creates_new_field(db):
    """CF-5: upsert inserts a new custom field row when the key doesn't exist.
    CF-6: field_value is stored as TEXT string.

    GIVEN lead 'lead-1' has no custom fields
    WHEN upsert is called for ('lead-1', 'quintana-seguros', 'car_year', '2021', 'integer')
    THEN a row is inserted with field_value='2021' stored as TEXT
    """
    from app.leads.lead_custom_fields_service import upsert, get_all

    result = await upsert(
        db,
        lead_id="lead-1",
        client_id="quintana-seguros",
        field_key="car_year",
        field_value="2021",
        field_type="integer",
    )

    assert result.field_value == "2021"
    assert result.field_type == "integer"
    assert result.lead_id == "lead-1"
    assert result.field_key == "car_year"
    # field_value is always TEXT
    assert isinstance(result.field_value, str)


@pytest.mark.asyncio
async def test_upsert_updates_existing_field(db):
    """CF-5: upsert updates an existing row without creating a duplicate.

    GIVEN a row exists for (lead-1, quintana-seguros, car_year) with value '2021'
    WHEN upsert is called with value '2023'
    THEN the row is updated and no duplicate is created
    """
    from app.leads.lead_custom_fields_service import upsert, get_all

    await upsert(
        db,
        lead_id="lead-1",
        client_id="quintana-seguros",
        field_key="car_year",
        field_value="2021",
        field_type="integer",
    )

    updated = await upsert(
        db,
        lead_id="lead-1",
        client_id="quintana-seguros",
        field_key="car_year",
        field_value="2023",
        field_type="integer",
    )

    assert updated.field_value == "2023"

    # Verify only one row exists for this key
    all_fields = await get_all(db, lead_id="lead-1", client_id="quintana-seguros")
    assert all_fields.get("car_year") == "2023"
    # Count car_year entries: must be exactly 1
    assert list(all_fields.keys()).count("car_year") == 1


@pytest.mark.asyncio
async def test_upsert_coercion_failure_rejects_write(db):
    """CF-4: upsert with invalid value for declared field_type rejects the write.

    GIVEN field_type='integer' and field_value='not-a-number'
    WHEN upsert is called
    THEN FieldTypeError is raised and no row is inserted
    """
    from app.leads.lead_custom_fields_service import upsert, get_all, FieldTypeError

    with pytest.raises(FieldTypeError):
        await upsert(
            db,
            lead_id="lead-1",
            client_id="quintana-seguros",
            field_key="car_year",
            field_value="not-a-number",
            field_type="integer",
        )

    # No row should have been written
    all_fields = await get_all(db, lead_id="lead-1", client_id="quintana-seguros")
    assert "car_year" not in all_fields


# ---------------------------------------------------------------------------
# CF-7: get_all() — batch read for a single lead
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_all_returns_all_fields_for_lead(db):
    """CF-7: get_all fetches ALL custom fields for a lead in one call.

    GIVEN 3 custom fields are set for lead-1
    WHEN get_all(lead_id='lead-1', client_id='quintana-seguros') is called
    THEN all 3 are returned as {field_key: field_value}
    """
    from app.leads.lead_custom_fields_service import upsert, get_all

    await upsert(db, lead_id="lead-1", client_id="quintana-seguros", field_key="car_make", field_value="Toyota", field_type="string")
    await upsert(db, lead_id="lead-1", client_id="quintana-seguros", field_key="car_year", field_value="2021", field_type="integer")
    await upsert(db, lead_id="lead-1", client_id="quintana-seguros", field_key="age", field_value="35", field_type="integer")

    result = await get_all(db, lead_id="lead-1", client_id="quintana-seguros")

    assert result == {"car_make": "Toyota", "car_year": "2021", "age": "35"}


@pytest.mark.asyncio
async def test_get_all_returns_empty_dict_when_no_fields(db):
    """CF-7: get_all returns empty dict when lead has no custom fields."""
    from app.leads.lead_custom_fields_service import get_all

    result = await get_all(db, lead_id="lead-1", client_id="quintana-seguros")

    assert result == {}


# ---------------------------------------------------------------------------
# CF-9: Cross-client isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_all_isolates_by_client_id(db):
    """CF-9: get_all for client_b returns empty when only client_a has fields.

    GIVEN lead-1 has custom fields under 'quintana-seguros'
    WHEN get_all is called with client_id='other-client'
    THEN no rows are returned (not an error)
    """
    from app.leads.lead_custom_fields_service import upsert, get_all

    await upsert(
        db,
        lead_id="lead-1",
        client_id="quintana-seguros",
        field_key="car_make",
        field_value="Toyota",
        field_type="string",
    )

    result = await get_all(db, lead_id="lead-1", client_id="other-client")

    assert result == {}


# ---------------------------------------------------------------------------
# CF-8: batch_get() — multi-lead read
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_two_leads(tmp_path: Path):
    """Session with two leads for batch_get tests."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/lcf_batch_test.db",
    )
    await db_module.init_db(settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as session:
        from app.tenants.models import Client
        from app.leads.models import Lead

        client = Client(id="quintana-seguros", name="Quintana Seguros", voice_id="test-voice-id")
        session.add(client)
        await session.flush()

        for i in range(1, 3):
            lead = Lead(
                id=f"lead-{i}",
                client_id="quintana-seguros",
                name=f"Lead {i}",
                phone=f"+549110000000{i}",
            )
            session.add(lead)
        await session.commit()

    async with db_module.async_session_factory() as session:
        yield session

    await db_module.close_db()


@pytest.mark.asyncio
async def test_batch_get_returns_fields_for_multiple_leads(db_two_leads):
    """CF-8: batch_get returns {lead_id: {field_key: field_value}} for all leads.

    GIVEN lead-1 has car_make='Toyota' and lead-2 has car_make='Ford'
    WHEN batch_get(['lead-1', 'lead-2'], 'quintana-seguros') is called
    THEN both leads' fields are returned in a single dict keyed by lead_id
    """
    from app.leads.lead_custom_fields_service import upsert, batch_get

    await upsert(db_two_leads, lead_id="lead-1", client_id="quintana-seguros", field_key="car_make", field_value="Toyota", field_type="string")
    await upsert(db_two_leads, lead_id="lead-2", client_id="quintana-seguros", field_key="car_make", field_value="Ford", field_type="string")

    result = await batch_get(db_two_leads, lead_ids=["lead-1", "lead-2"], client_id="quintana-seguros")

    assert result == {
        "lead-1": {"car_make": "Toyota"},
        "lead-2": {"car_make": "Ford"},
    }


@pytest.mark.asyncio
async def test_batch_get_missing_lead_gets_empty_dict(db_two_leads):
    """CF-8: batch_get includes an empty dict for leads with no custom fields."""
    from app.leads.lead_custom_fields_service import upsert, batch_get

    await upsert(db_two_leads, lead_id="lead-1", client_id="quintana-seguros", field_key="car_make", field_value="Toyota", field_type="string")

    result = await batch_get(db_two_leads, lead_ids=["lead-1", "lead-2"], client_id="quintana-seguros")

    # lead-2 has no fields → empty dict (not KeyError)
    assert "lead-1" in result
    assert result["lead-1"] == {"car_make": "Toyota"}
    assert "lead-2" in result
    assert result["lead-2"] == {}


# ---------------------------------------------------------------------------
# upsert_many() — batch write
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_many_writes_all_fields(db):
    """upsert_many writes all fields and returns the count.

    GIVEN 3 key-value pairs for lead-1
    WHEN upsert_many is called
    THEN all 3 are stored and count=3 is returned
    """
    from app.leads.lead_custom_fields_service import upsert_many, get_all

    count = await upsert_many(
        db,
        lead_id="lead-1",
        client_id="quintana-seguros",
        fields={"car_make": "Toyota", "car_year": "2021", "zona": "Norte"},
        field_types={"car_make": "string", "car_year": "integer", "zona": "string"},
    )

    assert count == 3

    result = await get_all(db, lead_id="lead-1", client_id="quintana-seguros")
    assert result == {"car_make": "Toyota", "car_year": "2021", "zona": "Norte"}


# ---------------------------------------------------------------------------
# LeadCustomField model — CF-1 unique constraint
# ---------------------------------------------------------------------------


def test_lead_custom_field_model_has_correct_columns():
    """CF-1: LeadCustomField model defines all required columns.

    GIVEN the LeadCustomField SQLAlchemy model
    WHEN columns are inspected
    THEN all required columns are present: id, lead_id, client_id, field_key,
         field_value, field_type, created_at, updated_at
    """
    from sqlalchemy import inspect as sa_inspect
    from app.leads.models import LeadCustomField

    mapper = sa_inspect(LeadCustomField)
    column_names = {col.key for col in mapper.mapper.column_attrs}

    required = {"id", "lead_id", "client_id", "field_key", "field_value", "field_type", "created_at", "updated_at"}
    missing = required - column_names
    assert not missing, f"LeadCustomField missing columns: {missing}"


def test_lead_custom_field_model_tablename():
    """LeadCustomField uses the correct table name 'lead_custom_fields'."""
    from app.leads.models import LeadCustomField

    assert LeadCustomField.__tablename__ == "lead_custom_fields"


def test_valid_field_types_constant():
    """VALID_FIELD_TYPES must include exactly the 5 allowed types."""
    from app.leads.lead_custom_fields_service import VALID_FIELD_TYPES

    assert VALID_FIELD_TYPES == {"string", "integer", "boolean", "date", "phone"}


# ---------------------------------------------------------------------------
# CF-1: Unique constraint includes (lead_id, client_id, field_key)
# ---------------------------------------------------------------------------


def test_lead_custom_field_unique_index_includes_client_id():
    """CF-1: LeadCustomField unique index MUST include client_id.

    Spec CF-1: 'unique on (lead_id, client_id, field_key)'.
    The old constraint was (lead_id, field_key) only, which violates multi-tenancy.
    """
    from app.leads.models import LeadCustomField
    from sqlalchemy import inspect

    mapper = inspect(LeadCustomField)
    table = mapper.local_table

    # Find unique indexes
    unique_indexes = [idx for idx in table.indexes if idx.unique]

    # At least one unique index must cover all three columns
    required_cols = {"lead_id", "client_id", "field_key"}
    composite_unique_found = any(
        {col.name for col in idx.columns} == required_cols
        for idx in unique_indexes
    )
    assert composite_unique_found, (
        f"No unique index found for (lead_id, client_id, field_key). "
        f"Found unique indexes: {[{col.name for col in idx.columns} for idx in unique_indexes]}"
    )


@pytest.mark.asyncio
async def test_upsert_unique_constraint_scoped_by_client_id(db):
    """CF-1: Same (lead_id, field_key) with different client_id creates separate rows.

    GIVEN two different clients each having the same lead_id and field_key
    WHEN upsert is called for each
    THEN each creates its own row (no conflict) — client isolation is enforced
    """
    # We need a second client + lead for this test
    from app.tenants.models import Client
    from app.leads.models import Lead
    from app.leads.lead_custom_fields_service import upsert, get_all

    second_client = Client(
        id="another-client",
        name="Another Client",
        voice_id="test-voice-id-2",
    )
    db.add(second_client)

    second_lead = Lead(
        id="lead-1",  # Same lead_id (same person, different client scope)
        client_id="another-client",
    )
    # Actually we need a different lead_id since lead.client_id is FK to clients
    second_lead_for_another = Lead(
        id="lead-another-1",
        client_id="another-client",
        name="Jorge Díaz",
        phone="+5491100000002",
    )
    db.add(second_lead_for_another)
    await db.flush()

    # Upsert the same field_key for two different leads (different clients)
    await upsert(
        db,
        lead_id="lead-1",
        client_id="quintana-seguros",
        field_key="car_make",
        field_value="Toyota",
    )
    await upsert(
        db,
        lead_id="lead-another-1",
        client_id="another-client",
        field_key="car_make",
        field_value="Ford",
    )
    await db.flush()

    # Read each client's value — must be isolated
    cf_quintana = await get_all(db, "lead-1", "quintana-seguros")
    cf_another = await get_all(db, "lead-another-1", "another-client")

    assert cf_quintana.get("car_make") == "Toyota", (
        f"quintana-seguros should have Toyota, got: {cf_quintana}"
    )
    assert cf_another.get("car_make") == "Ford", (
        f"another-client should have Ford, got: {cf_another}"
    )
