"""Unit + integration tests for the structured data corrections pipeline.

TDD: RED → GREEN → TRIANGULATE → REFACTOR for each phase.

Tasks covered:
- 1.1  Lead.email and Lead.age columns (nullable, persist, default NULL)
- 1.2  Migration script: adds email/age columns idempotently
- 2.1  DataCorrection / DataCorrectionsAxis schemas + CORRECTABLE_FIELDS registry
- 2.2  Per-field validators (phone, car_year, name, email, age)
- 2.3  Unknown-field rejection and type coercion
- 3.1  run_data_corrections_pipeline() async pipeline (mocked OpenAI)
- 3.2  Mock OpenAI: no-op, single-field, multi-field
- 3.3  Idempotency, disabled confidence gate, audit-ready corrections
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# 1.1  Lead model — email / age columns
# ---------------------------------------------------------------------------


def test_lead_has_email_column() -> None:
    """Lead model MUST have a nullable String `email` column."""
    from app.leads.models import Lead
    from sqlalchemy import inspect, String

    mapper = inspect(Lead)
    col_names = [c.key for c in mapper.mapper.column_attrs]
    assert "email" in col_names, "Lead model must have an `email` column"

    col = mapper.mapper.column_attrs["email"].columns[0]
    assert col.nullable is True, "Lead.email must be nullable"
    # SQLAlchemy maps String → VARCHAR; just check type name
    assert isinstance(col.type, String), "Lead.email must be String type"


def test_lead_has_age_column() -> None:
    """Lead model MUST have a nullable Integer `age` column."""
    from app.leads.models import Lead
    from sqlalchemy import inspect, Integer

    mapper = inspect(Lead)
    col_names = [c.key for c in mapper.mapper.column_attrs]
    assert "age" in col_names, "Lead model must have an `age` column"

    col = mapper.mapper.column_attrs["age"].columns[0]
    assert col.nullable is True, "Lead.age must be nullable"
    assert isinstance(col.type, Integer), "Lead.age must be Integer type"


@pytest_asyncio.fixture
async def lead_db(tmp_path: Path):
    """Isolated SQLite DB with quintana-seguros + one test lead."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/dc_test.db",
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
            name="DC Test Lead",
            phone="+5411000099",
            lead_id="dc-lead-001",
        )
        await sess.commit()

    yield db_module
    await db_module.close_db()


async def test_lead_email_defaults_null(lead_db) -> None:
    """Newly created lead MUST have email=None by default."""
    from app.leads.models import Lead
    from sqlalchemy import select

    assert lead_db.async_session_factory is not None
    async with lead_db.async_session_factory() as sess:
        result = await sess.execute(select(Lead).where(Lead.id == "dc-lead-001"))
        lead = result.scalar_one()
        assert lead.email is None, "Lead.email must default to NULL"


async def test_lead_age_defaults_null(lead_db) -> None:
    """Newly created lead MUST have age=None by default."""
    from app.leads.models import Lead
    from sqlalchemy import select

    assert lead_db.async_session_factory is not None
    async with lead_db.async_session_factory() as sess:
        result = await sess.execute(select(Lead).where(Lead.id == "dc-lead-001"))
        lead = result.scalar_one()
        assert lead.age is None, "Lead.age must default to NULL"


async def test_lead_email_persists(lead_db) -> None:
    """Setting Lead.email and committing MUST persist the value."""
    from app.leads.models import Lead
    from sqlalchemy import select

    assert lead_db.async_session_factory is not None
    async with lead_db.async_session_factory() as sess:
        result = await sess.execute(select(Lead).where(Lead.id == "dc-lead-001"))
        lead = result.scalar_one()
        lead.email = "test@example.com"
        await sess.commit()

    async with lead_db.async_session_factory() as sess:
        result = await sess.execute(select(Lead).where(Lead.id == "dc-lead-001"))
        lead = result.scalar_one()
        assert lead.email == "test@example.com"


async def test_lead_age_persists(lead_db) -> None:
    """Setting Lead.age and committing MUST persist the integer value."""
    from app.leads.models import Lead
    from sqlalchemy import select

    assert lead_db.async_session_factory is not None
    async with lead_db.async_session_factory() as sess:
        result = await sess.execute(select(Lead).where(Lead.id == "dc-lead-001"))
        lead = result.scalar_one()
        lead.age = 35
        await sess.commit()

    async with lead_db.async_session_factory() as sess:
        result = await sess.execute(select(Lead).where(Lead.id == "dc-lead-001"))
        lead = result.scalar_one()
        assert lead.age == 35


# ---------------------------------------------------------------------------
# 1.2  Migration script — idempotent ALTER TABLE
# ---------------------------------------------------------------------------


async def test_migration_adds_email_and_age_columns(tmp_path: Path) -> None:
    """Migration MUST add email TEXT and age INTEGER to the leads table."""
    import sqlalchemy

    db_url = f"sqlite+aiosqlite:///{tmp_path}/migration_test.db"

    # Bootstrap schema WITHOUT the new columns (simulate pre-migration DB)
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        # Minimal leads table without email/age (simulate old schema)
        await conn.execute(
            sqlalchemy.text(
                "CREATE TABLE IF NOT EXISTS leads ("
                "id TEXT PRIMARY KEY,"
                "name TEXT NOT NULL,"
                "phone TEXT NOT NULL"
                ")"
            )
        )
    await engine.dispose()

    # Run migration
    from scripts.migrate_data_corrections import run_migration

    await run_migration(db_url)

    # Verify columns exist
    engine2 = create_async_engine(db_url)
    async with engine2.begin() as conn:
        result = await conn.execute(sqlalchemy.text("PRAGMA table_info(leads)"))
        cols = {row[1] for row in result.fetchall()}
    await engine2.dispose()

    assert "email" in cols, "Migration must add email column to leads"
    assert "age" in cols, "Migration must add age column to leads"


async def test_migration_is_idempotent(tmp_path: Path) -> None:
    """Running migration TWICE must NOT raise and must still have both columns."""
    import sqlalchemy

    db_url = f"sqlite+aiosqlite:///{tmp_path}/migration_idempotent.db"

    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        await conn.execute(
            sqlalchemy.text(
                "CREATE TABLE IF NOT EXISTS leads ("
                "id TEXT PRIMARY KEY,"
                "name TEXT NOT NULL"
                ")"
            )
        )
    await engine.dispose()

    from scripts.migrate_data_corrections import run_migration

    # First run
    await run_migration(db_url)
    # Second run — must not raise
    await run_migration(db_url)

    engine2 = create_async_engine(db_url)
    async with engine2.begin() as conn:
        result = await conn.execute(sqlalchemy.text("PRAGMA table_info(leads)"))
        cols = {row[1] for row in result.fetchall()}
    await engine2.dispose()

    assert "email" in cols
    assert "age" in cols


# ---------------------------------------------------------------------------
# 2.1  DataCorrection / DataCorrectionsAxis schema + CORRECTABLE_FIELDS registry
# ---------------------------------------------------------------------------


def test_data_correction_model_has_required_fields() -> None:
    """DataCorrection MUST have field, current_value, corrected_value, confidence, evidence, applied."""
    from app.analysis.universal.data_corrections import DataCorrection

    dc = DataCorrection(
        field="name",
        current_value="Juan",
        corrected_value="Juan Carlos",
        confidence=0.9,
        evidence="Soy Juan Carlos, no Juan",
        applied=False,
    )
    assert dc.field == "name"
    assert dc.current_value == "Juan"
    assert dc.corrected_value == "Juan Carlos"
    assert dc.confidence == 0.9
    assert dc.evidence == "Soy Juan Carlos, no Juan"
    assert dc.applied is False


def test_data_corrections_axis_has_corrections_list() -> None:
    """DataCorrectionsAxis MUST have corrections: list[DataCorrection]."""
    from app.analysis.universal.data_corrections import (
        DataCorrectionsAxis,
        DataCorrection,
    )

    axis = DataCorrectionsAxis(
        corrections=[
            DataCorrection(
                field="email",
                current_value=None,
                corrected_value="juan@example.com",
                confidence=0.95,
                evidence="Mi email es juan@example.com",
                applied=True,
            )
        ]
    )
    assert len(axis.corrections) == 1
    assert axis.corrections[0].field == "email"


def test_data_corrections_axis_empty_by_default() -> None:
    """DataCorrectionsAxis() with no args MUST have empty corrections list."""
    from app.analysis.universal.data_corrections import DataCorrectionsAxis

    axis = DataCorrectionsAxis()
    assert axis.corrections == []


def test_correctable_fields_registry_has_all_9_fields() -> None:
    """CORRECTABLE_FIELDS MUST contain all 9 allowed fields (zona added in PR 1)."""
    from app.analysis.universal.data_corrections import CORRECTABLE_FIELDS

    expected = {
        "name",
        "phone",
        "car_make",
        "car_model",
        "car_year",
        "current_insurance",
        "email",
        "age",
        "zona",  # Added: post-call-analysis-bi-friendly PR 1
    }
    assert (
        set(CORRECTABLE_FIELDS.keys()) == expected
    ), f"Registry mismatch. Got: {set(CORRECTABLE_FIELDS.keys())}"


def test_correctable_fields_registry_entry_structure() -> None:
    """Each CORRECTABLE_FIELDS entry MUST have lead_attr, type, crm_field."""
    from app.analysis.universal.data_corrections import CORRECTABLE_FIELDS

    for field_name, entry in CORRECTABLE_FIELDS.items():
        assert hasattr(entry, "lead_attr"), f"{field_name} entry missing lead_attr"
        assert hasattr(entry, "type"), f"{field_name} entry missing type"
        assert hasattr(entry, "crm_field"), f"{field_name} entry missing crm_field"


def test_correctable_fields_email_entry() -> None:
    """CORRECTABLE_FIELDS['email'] MUST map to lead_attr='email', type='str'."""
    from app.analysis.universal.data_corrections import CORRECTABLE_FIELDS

    entry = CORRECTABLE_FIELDS["email"]
    assert entry.lead_attr == "email"
    assert entry.type == "str"


def test_correctable_fields_age_entry() -> None:
    """CORRECTABLE_FIELDS['age'] MUST map to lead_attr='age', type='int'."""
    from app.analysis.universal.data_corrections import CORRECTABLE_FIELDS

    entry = CORRECTABLE_FIELDS["age"]
    assert entry.lead_attr == "age"
    assert entry.type == "int"


def test_correctable_fields_car_year_type() -> None:
    """CORRECTABLE_FIELDS['car_year'] MUST have type='int'."""
    from app.analysis.universal.data_corrections import CORRECTABLE_FIELDS

    assert CORRECTABLE_FIELDS["car_year"].type == "int"


# ---------------------------------------------------------------------------
# 2.2  Per-field validators
# ---------------------------------------------------------------------------


def test_validate_phone_valid_e164() -> None:
    """Valid E.164 phone passes validation."""
    from app.analysis.universal.data_corrections import _validate_phone

    ok, _ = _validate_phone("+5411234567890")
    assert ok is True


def test_validate_phone_valid_10digit() -> None:
    """Valid 10-digit phone passes validation."""
    from app.analysis.universal.data_corrections import _validate_phone

    ok, _ = _validate_phone("1234567890")
    assert ok is True


def test_validate_phone_invalid_too_short() -> None:
    """Phone with fewer than 10 digits fails validation."""
    from app.analysis.universal.data_corrections import _validate_phone

    ok, err = _validate_phone("12345")
    assert ok is False
    assert err is not None and len(err) > 0


def test_validate_car_year_valid() -> None:
    """Car year 2020 passes validation."""
    from app.analysis.universal.data_corrections import _validate_car_year

    ok, _ = _validate_car_year("2020")
    assert ok is True


def test_validate_car_year_invalid_too_old() -> None:
    """Car year 1850 fails validation (< 1900)."""
    from app.analysis.universal.data_corrections import _validate_car_year

    ok, err = _validate_car_year("1850")
    assert ok is False
    assert err is not None


def test_validate_car_year_invalid_too_new() -> None:
    """Car year 2999 fails validation (> 2030)."""
    from app.analysis.universal.data_corrections import _validate_car_year

    ok, err = _validate_car_year("2999")
    assert ok is False


def test_validate_car_year_non_numeric() -> None:
    """Non-numeric car year fails validation."""
    from app.analysis.universal.data_corrections import _validate_car_year

    ok, err = _validate_car_year("twenty-twenty")
    assert ok is False


def test_validate_name_valid() -> None:
    """Non-empty name passes validation."""
    from app.analysis.universal.data_corrections import _validate_name

    ok, _ = _validate_name("Juan Carlos")
    assert ok is True


def test_validate_name_empty() -> None:
    """Empty/whitespace-only name fails validation."""
    from app.analysis.universal.data_corrections import _validate_name

    ok, err = _validate_name("   ")
    assert ok is False
    assert err is not None


def test_validate_email_valid() -> None:
    """Standard email format passes validation."""
    from app.analysis.universal.data_corrections import _validate_email

    ok, _ = _validate_email("juan@example.com")
    assert ok is True


def test_validate_email_invalid_no_at() -> None:
    """Email without @ fails validation."""
    from app.analysis.universal.data_corrections import _validate_email

    ok, err = _validate_email("juanexample.com")
    assert ok is False
    assert err is not None


def test_validate_email_invalid_no_domain() -> None:
    """Email without domain (e.g. 'juan@') fails validation."""
    from app.analysis.universal.data_corrections import _validate_email

    ok, err = _validate_email("juan@")
    assert ok is False


def test_validate_age_valid() -> None:
    """Age 35 passes validation."""
    from app.analysis.universal.data_corrections import _validate_age

    ok, _ = _validate_age("35")
    assert ok is True


def test_validate_age_zero() -> None:
    """Age 0 fails validation (< 1)."""
    from app.analysis.universal.data_corrections import _validate_age

    ok, err = _validate_age("0")
    assert ok is False
    assert err is not None


def test_validate_age_too_large() -> None:
    """Age 200 fails validation (> 120)."""
    from app.analysis.universal.data_corrections import _validate_age

    ok, err = _validate_age("200")
    assert ok is False


def test_validate_age_non_numeric() -> None:
    """Non-numeric age fails validation."""
    from app.analysis.universal.data_corrections import _validate_age

    ok, err = _validate_age("thirty-five")
    assert ok is False


def test_validate_age_with_unit_suffix() -> None:
    """Bug #93: '30 años' must parse to a valid age, not be dropped."""
    from app.analysis.universal.data_corrections import _validate_age

    ok, err = _validate_age("30 años")
    assert ok is True
    assert err is None


def test_validate_age_with_approx() -> None:
    """'30 aprox' must parse — extract the embedded integer."""
    from app.analysis.universal.data_corrections import _validate_age

    ok, _ = _validate_age("30 aprox")
    assert ok is True


def test_validate_age_word_returns_false() -> None:
    """No digits ('treinta') → reject gracefully, never crash."""
    from app.analysis.universal.data_corrections import _validate_age

    ok, err = _validate_age("treinta")
    assert ok is False
    assert err is not None


def test_validate_age_embedded_out_of_range() -> None:
    """'200 años' extracts 200 → still rejected for being out of range."""
    from app.analysis.universal.data_corrections import _validate_age

    ok, err = _validate_age("200 años")
    assert ok is False
    assert err is not None


def test_validate_car_year_with_suffix() -> None:
    """Same latent bug as age — '2019 aprox' must parse."""
    from app.analysis.universal.data_corrections import _validate_car_year

    ok, _ = _validate_car_year("2019 aprox")
    assert ok is True


# ---------------------------------------------------------------------------
# 2.3  Unknown-field rejection and type coercion
# ---------------------------------------------------------------------------


def test_unknown_field_rejected_from_registry() -> None:
    """Fields not in CORRECTABLE_FIELDS MUST NOT be in the registry."""
    from app.analysis.universal.data_corrections import CORRECTABLE_FIELDS

    assert "address" not in CORRECTABLE_FIELDS
    assert "zip_code" not in CORRECTABLE_FIELDS


def test_coerce_int_field_returns_int() -> None:
    """coerce_value for int type field returns an int."""
    from app.analysis.universal.data_corrections import coerce_value

    result = coerce_value("2022", "int")
    assert isinstance(result, int)
    assert result == 2022


def test_coerce_str_field_returns_str() -> None:
    """coerce_value for str type field returns a str."""
    from app.analysis.universal.data_corrections import coerce_value

    result = coerce_value("Toyota", "str")
    assert isinstance(result, str)
    assert result == "Toyota"


def test_coerce_invalid_int_raises_value_error() -> None:
    """coerce_value for int type with non-numeric string raises ValueError."""
    from app.analysis.universal.data_corrections import coerce_value

    with pytest.raises((ValueError, TypeError)):
        coerce_value("not-a-number", "int")


def test_coerce_int_extracts_from_text() -> None:
    """Bug #93: coercion must extract the int from '30 años'."""
    from app.analysis.universal.data_corrections import coerce_value

    assert coerce_value("30 años", "int") == 30


def test_coerce_int_no_digits_raises() -> None:
    """coerce_value for int with no digits ('treinta') raises ValueError."""
    from app.analysis.universal.data_corrections import coerce_value

    with pytest.raises(ValueError):
        coerce_value("treinta", "int")


# ---------------------------------------------------------------------------
# 3.1 / 3.2  run_data_corrections_pipeline() — mocked OpenAI
# ---------------------------------------------------------------------------


async def test_pipeline_returns_empty_when_no_corrections() -> None:
    """Pipeline with GPT returning empty corrections MUST return empty axis."""
    from unittest.mock import AsyncMock, MagicMock
    from app.analysis.universal.data_corrections import (
        run_data_corrections_pipeline,
        DataCorrectionsAxis,
    )

    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.parsed = DataCorrectionsAxis(corrections=[])
    mock_client.beta.chat.completions.parse = AsyncMock(return_value=mock_response)

    result = await run_data_corrections_pipeline(
        transcript="Hola, gracias por llamar.",
        client=mock_client,
        current_lead_data={"name": "Juan", "phone": "+541123456789"},
    )

    assert isinstance(result, DataCorrectionsAxis)
    assert result.corrections == []


async def test_pipeline_returns_name_correction() -> None:
    """Pipeline MUST return DataCorrection for name field when GPT extracts one."""
    from unittest.mock import AsyncMock, MagicMock
    from app.analysis.universal.data_corrections import (
        run_data_corrections_pipeline,
        DataCorrectionsAxis,
        DataCorrection,
    )

    name_correction = DataCorrection(
        field="name",
        current_value="Juan",
        corrected_value="Juan Carlos",
        confidence=0.95,
        evidence="Me llamo Juan Carlos, no Juan",
        applied=False,
    )
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.parsed = DataCorrectionsAxis(
        corrections=[name_correction]
    )
    mock_client.beta.chat.completions.parse = AsyncMock(return_value=mock_response)

    result = await run_data_corrections_pipeline(
        transcript="Me llamo Juan Carlos, no Juan.",
        client=mock_client,
        current_lead_data={"name": "Juan"},
    )

    assert len(result.corrections) == 1
    assert result.corrections[0].field == "name"
    assert result.corrections[0].corrected_value == "Juan Carlos"
    assert result.corrections[0].applied is True  # passes validation, should be applied


async def test_pipeline_returns_multiple_corrections() -> None:
    """Pipeline MUST handle multiple corrections in one call."""
    from unittest.mock import AsyncMock, MagicMock
    from app.analysis.universal.data_corrections import (
        run_data_corrections_pipeline,
        DataCorrectionsAxis,
        DataCorrection,
    )

    corrections = [
        DataCorrection(
            field="name",
            current_value="Juan",
            corrected_value="Juan Carlos",
            confidence=0.9,
            evidence="Me llamo Juan Carlos",
            applied=False,
        ),
        DataCorrection(
            field="email",
            current_value=None,
            corrected_value="juan@example.com",
            confidence=0.95,
            evidence="Mi email es juan@example.com",
            applied=False,
        ),
        DataCorrection(
            field="car_year",
            current_value="2018",
            corrected_value="2019",
            confidence=0.85,
            evidence="El auto es del 2019, no 2018",
            applied=False,
        ),
    ]
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.parsed = DataCorrectionsAxis(
        corrections=corrections
    )
    mock_client.beta.chat.completions.parse = AsyncMock(return_value=mock_response)

    result = await run_data_corrections_pipeline(
        transcript="...",
        client=mock_client,
        current_lead_data={"name": "Juan", "car_year": 2018},
    )

    assert len(result.corrections) == 3
    fields = {c.field for c in result.corrections}
    assert fields == {"name", "email", "car_year"}
    # All three should be applied (pass validation)
    assert all(c.applied is True for c in result.corrections)


# ---------------------------------------------------------------------------
# 3.3  Idempotency, confidence gate (disabled), audit
# ---------------------------------------------------------------------------


async def test_pipeline_idempotency_drops_same_value() -> None:
    """Correction where corrected_value == current_value MUST be dropped."""
    from unittest.mock import AsyncMock, MagicMock
    from app.analysis.universal.data_corrections import (
        run_data_corrections_pipeline,
        DataCorrectionsAxis,
        DataCorrection,
    )

    same_value_correction = DataCorrection(
        field="car_make",
        current_value="Toyota",
        corrected_value="Toyota",  # Same as current
        confidence=0.9,
        evidence="Es un Toyota",
        applied=False,
    )
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.parsed = DataCorrectionsAxis(
        corrections=[same_value_correction]
    )
    mock_client.beta.chat.completions.parse = AsyncMock(return_value=mock_response)

    result = await run_data_corrections_pipeline(
        transcript="Es un Toyota.",
        client=mock_client,
        current_lead_data={"car_make": "Toyota"},
    )

    # Idempotency: correction where corrected == current must be dropped
    assert (
        result.corrections == []
    ), "Same-value correction must be dropped by idempotency gate"


async def test_pipeline_confidence_gate_disabled() -> None:
    """Even low confidence (< 0.8) corrections MUST be applied (gate disabled)."""
    from unittest.mock import AsyncMock, MagicMock
    from app.analysis.universal.data_corrections import (
        run_data_corrections_pipeline,
        DataCorrectionsAxis,
        DataCorrection,
    )

    low_confidence = DataCorrection(
        field="name",
        current_value="Juan",
        corrected_value="Carlos",
        confidence=0.3,  # Below future threshold of 0.8
        evidence="Creo que dijo Carlos",
        applied=False,
    )
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.parsed = DataCorrectionsAxis(
        corrections=[low_confidence]
    )
    mock_client.beta.chat.completions.parse = AsyncMock(return_value=mock_response)

    result = await run_data_corrections_pipeline(
        transcript="...",
        client=mock_client,
        current_lead_data={"name": "Juan"},
    )

    assert len(result.corrections) == 1
    assert (
        result.corrections[0].applied is True
    ), "Confidence gate is disabled (threshold=0.0); low confidence must still be applied"


async def test_pipeline_invalid_car_year_not_applied() -> None:
    """Correction with invalid car_year (out of range) MUST have applied=False."""
    from unittest.mock import AsyncMock, MagicMock
    from app.analysis.universal.data_corrections import (
        run_data_corrections_pipeline,
        DataCorrectionsAxis,
        DataCorrection,
    )

    bad_year = DataCorrection(
        field="car_year",
        current_value="2020",
        corrected_value="1850",  # Out of range
        confidence=0.9,
        evidence="El auto es del 1850",
        applied=False,
    )
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.parsed = DataCorrectionsAxis(
        corrections=[bad_year]
    )
    mock_client.beta.chat.completions.parse = AsyncMock(return_value=mock_response)

    result = await run_data_corrections_pipeline(
        transcript="...",
        client=mock_client,
        current_lead_data={"car_year": 2020},
    )

    assert len(result.corrections) == 1
    assert (
        result.corrections[0].applied is False
    ), "Invalid car_year must have applied=False"


async def test_pipeline_unknown_field_silently_dropped() -> None:
    """Field not in CORRECTABLE_FIELDS MUST be silently dropped (not returned)."""
    from unittest.mock import AsyncMock, MagicMock
    from app.analysis.universal.data_corrections import (
        run_data_corrections_pipeline,
        DataCorrectionsAxis,
        DataCorrection,
    )

    unknown_field = DataCorrection(
        field="address",  # Not in registry
        current_value=None,
        corrected_value="Calle Falsa 123",
        confidence=0.9,
        evidence="Vivo en Calle Falsa 123",
        applied=False,
    )
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.parsed = DataCorrectionsAxis(
        corrections=[unknown_field]
    )
    mock_client.beta.chat.completions.parse = AsyncMock(return_value=mock_response)

    result = await run_data_corrections_pipeline(
        transcript="...",
        client=mock_client,
        current_lead_data={},
    )

    assert result.corrections == [], "Unknown field must be silently dropped"


async def test_pipeline_returns_empty_on_exception() -> None:
    """Pipeline MUST return empty DataCorrectionsAxis (not raise) on OpenAI error."""
    from unittest.mock import AsyncMock
    from app.analysis.universal.data_corrections import (
        run_data_corrections_pipeline,
        DataCorrectionsAxis,
    )

    mock_client = AsyncMock()
    mock_client.beta.chat.completions.parse = AsyncMock(
        side_effect=Exception("OpenAI timeout")
    )

    result = await run_data_corrections_pipeline(
        transcript="...",
        client=mock_client,
        current_lead_data={},
    )

    assert isinstance(result, DataCorrectionsAxis)
    assert result.corrections == []


# ---------------------------------------------------------------------------
# Fix: rejection_reason field on DataCorrection model
# ---------------------------------------------------------------------------


def test_data_correction_has_rejection_reason_field() -> None:
    """DataCorrection MUST have a nullable rejection_reason field (defaults None)."""
    from app.analysis.universal.data_corrections import DataCorrection

    dc = DataCorrection(
        field="name",
        current_value="Juan",
        corrected_value="Juan Carlos",
        confidence=0.9,
        evidence="Me llamo Juan Carlos",
        applied=True,
    )
    # Must exist and default to None
    assert hasattr(dc, "rejection_reason")
    assert dc.rejection_reason is None


def test_data_correction_rejection_reason_populated_when_set() -> None:
    """DataCorrection rejection_reason MUST accept a string value."""
    from app.analysis.universal.data_corrections import DataCorrection

    dc = DataCorrection(
        field="age",
        current_value=None,
        corrected_value="200",
        confidence=0.9,
        evidence="Tengo 200 años",
        applied=False,
        rejection_reason="age out of range 0-120",
    )
    assert dc.rejection_reason == "age out of range 0-120"
    assert dc.applied is False


# ---------------------------------------------------------------------------
# Fix: _process_corrections populates rejection_reason on validation failure
# ---------------------------------------------------------------------------


def test_process_corrections_sets_rejection_reason_on_invalid_age() -> None:
    """_process_corrections MUST set rejection_reason when age is out of range."""
    from app.analysis.universal.data_corrections import (
        _process_corrections,
        DataCorrection,
    )

    invalid_age = DataCorrection(
        field="age",
        current_value=None,
        corrected_value="200",
        confidence=0.9,
        evidence="Tengo 200 años",
        applied=False,
    )

    result = _process_corrections([invalid_age], {})

    assert len(result) == 1
    assert result[0].applied is False
    assert result[0].rejection_reason is not None
    assert len(result[0].rejection_reason) > 0


def test_process_corrections_no_rejection_reason_when_valid() -> None:
    """_process_corrections MUST leave rejection_reason=None for valid corrections."""
    from app.analysis.universal.data_corrections import (
        _process_corrections,
        DataCorrection,
    )

    valid_email = DataCorrection(
        field="email",
        current_value=None,
        corrected_value="juan@example.com",
        confidence=0.9,
        evidence="Mi email es juan@example.com",
        applied=False,
    )

    result = _process_corrections([valid_email], {})

    assert len(result) == 1
    assert result[0].applied is True
    assert result[0].rejection_reason is None


# ---------------------------------------------------------------------------
# Fix: _apply_structured_corrections returns ALL corrections (applied + rejected)
# ---------------------------------------------------------------------------


def test_apply_structured_corrections_returns_all_corrections() -> None:
    """_apply_structured_corrections MUST return ALL corrections, not just applied ones."""
    from unittest.mock import MagicMock
    from app.summarizer import _apply_structured_corrections
    from app.analysis.universal.data_corrections import DataCorrection

    mock_lead = MagicMock()
    mock_lead.name = "Juan"
    mock_lead.phone = "+5411000099"
    mock_lead.email = None
    mock_lead.age = None
    mock_lead.car_make = "Toyota"
    mock_lead.car_model = None
    mock_lead.car_year = None
    mock_lead.current_insurance = None

    corrections = [
        DataCorrection(
            field="email",
            current_value=None,
            corrected_value="juan@example.com",
            confidence=0.9,
            evidence="Mi email es juan@example.com",
            applied=True,  # valid → should be applied
        ),
        DataCorrection(
            field="age",
            current_value=None,
            corrected_value="200",  # invalid
            confidence=0.9,
            evidence="Tengo 200 años",
            applied=False,
            rejection_reason="age out of range 0-120",
        ),
    ]

    result = _apply_structured_corrections(mock_lead, corrections)

    # Must return ALL 2 corrections, not just the applied one
    assert len(result) == 2, f"Expected 2 corrections in audit, got {len(result)}"

    applied = [c for c in result if c.applied]
    rejected = [c for c in result if not c.applied]

    assert len(applied) == 1
    assert applied[0].field == "email"

    assert len(rejected) == 1
    assert rejected[0].field == "age"
    assert rejected[0].rejection_reason is not None


def test_apply_structured_corrections_rejected_has_reason() -> None:
    """Rejected corrections in the returned list MUST have rejection_reason set."""
    from unittest.mock import MagicMock
    from app.summarizer import _apply_structured_corrections
    from app.analysis.universal.data_corrections import DataCorrection

    mock_lead = MagicMock()

    corrections = [
        DataCorrection(
            field="car_year",
            current_value="2020",
            corrected_value="1850",
            confidence=0.9,
            evidence="El auto es del 1850",
            applied=False,
            rejection_reason="car year 1850 is before 1900",
        ),
    ]

    result = _apply_structured_corrections(mock_lead, corrections)

    assert len(result) == 1
    assert result[0].applied is False
    assert result[0].rejection_reason == "car year 1850 is before 1900"
