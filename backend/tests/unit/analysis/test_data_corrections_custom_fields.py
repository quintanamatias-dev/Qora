"""Unit tests for WU-4 task 4.2: custom-field data corrections.

TDD: RED → GREEN → TRIANGULATE → REFACTOR

Spec requirements covered:
- Spec §6: current_lead_data snapshot includes base Lead fields + custom fields
- Spec §6: CORRECTABLE_FIELDS for car_make, car_model, car_year, current_insurance, age
  must DUAL-WRITE: corrections go to lead_custom_fields AND legacy Lead ORM columns
- CorrectableField must support a 'storage' attribute to distinguish custom vs lead_attr writes
- Missing crm.yaml → corrections for custom fields still write to lead_custom_fields
"""

from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def cf_corr_db(tmp_path: Path):
    """Isolated SQLite DB with quintana-seguros + one test lead with custom fields."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/cf_corr_test.db",
    )
    from tests.helpers.migrations import init_db_with_migrations as _init_db_with_migrations
    await _init_db_with_migrations(db_module, settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead
        from app.leads.lead_custom_fields_service import upsert as upsert_cf

        await seed_quintana(sess)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Maria Garcia",
            phone="+5411000099",
            lead_id="cf-corr-lead-001",
        )
        # Pre-seed some custom fields for the lead
        await upsert_cf(
            sess,
            lead_id="cf-corr-lead-001",
            client_id="quintana-seguros",
            field_key="car_make",
            field_value="Toyota",
            field_type="string",
        )
        await upsert_cf(
            sess,
            lead_id="cf-corr-lead-001",
            client_id="quintana-seguros",
            field_key="car_year",
            field_value="2019",
            field_type="integer",
        )
        await sess.commit()

    yield db_module
    await db_module.close_db()


async def _make_cf_session(db_module, *, turns):
    from app.calls.service import create_session, add_transcript_turn

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        cs = await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id="cf-corr-lead-001",
        )
        cs.status = "completed"
        for role, content in turns:
            await add_transcript_turn(sess, cs.id, role, content)
        await sess.commit()
        return cs.id


def _make_cf_mock_client(analysis_obj):
    """Build a mock client that handles all pipeline schemas."""
    from app.analysis.universal import DIMENSION_MODULES
    from app.analysis.universal.interest.interests import InterestsAxis
    from app.analysis.universal.interest.interest_level import InterestLevelResult
    from app.analysis.universal.data_corrections import DataCorrectionsAxis as _DCA

    schema_to_target = {
        mod.DIMENSION["schema"]: mod.DIMENSION["target_field"]
        for mod in DIMENSION_MODULES
    }

    from tests.unit.test_summarizer import _axis_for_dimension

    async def _dispatch(*_args, response_format=None, **_kwargs):
        if response_format is _DCA:
            return _mock_resp(_DCA(corrections=[]))
        if response_format is InterestsAxis:
            return _mock_resp(analysis_obj.detected_interests)
        if response_format is InterestLevelResult:
            il = analysis_obj.interest_level or 0
            from app.analysis.universal.interest.interest_level import ProductScore as _PS

            axis_value = InterestLevelResult.model_construct(
                per_product=[
                    _PS.model_construct(
                        product="auto_todo_riesgo", score=il, reason="M."
                    )
                ]
                if il > 0
                else [],
                general_score=il,
                level="high" if il >= 61 else "medium" if il >= 41 else "low",
                reason="Mock.",
                positive_signals=[],
                negative_signals=[],
                confidence="medium",
            )
            return _mock_resp(axis_value)
        target_field = schema_to_target.get(response_format)
        if target_field is None:
            axis_value = analysis_obj
        else:
            axis_value = _axis_for_dimension(analysis_obj, target_field, response_format)
        return _mock_resp(axis_value)

    mock_client = AsyncMock()
    mock_client.beta.chat.completions.parse = AsyncMock(side_effect=_dispatch)
    mock_client.chat.completions.parse = mock_client.beta.chat.completions.parse
    return mock_client


def _mock_resp(parsed_value):
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.parsed = parsed_value
    resp.choices[0].message.refusal = None
    return resp


def _base_cf_analysis():
    from app.analysis_schema import PostCallAnalysis, CallOutcome, IdentifiedProblem
    from app.analysis.universal.interest.interests import InterestsAxis
    from app.analysis.universal.objections import ObjectionsAxis

    return PostCallAnalysis(
        summary="Test call with custom fields.",
        objections=ObjectionsAxis(),
        interest_level=70,
        current_insurance=None,
        next_action_suggested="call_again",
        call_outcome=CallOutcome(
            classification="completed_neutral",
            reason="Test.",
            confidence="medium",
        ),
        detected_interests=InterestsAxis(),
        identified_problem=IdentifiedProblem(
            primary_need="Test.",
            urgency="low",
        ),
    )


# ---------------------------------------------------------------------------
# Tests for current_lead_data snapshot merger (custom fields + base)
# ---------------------------------------------------------------------------


async def test_snapshot_includes_custom_fields(cf_corr_db):
    """current_lead_data snapshot passed to pipeline MUST include custom field values.

    Spec §6: snapshot merges base Lead fields + all custom fields for the lead.
    The pipeline receives car_make='Toyota' and car_year='2019' from custom fields.
    """
    from app.summarizer import generate_summary_and_facts
    from app.analysis.universal.data_corrections import DataCorrectionsAxis

    session_id = await _make_cf_session(
        cf_corr_db,
        turns=[("agent", "Hola"), ("user", "El auto es Toyota")],
    )

    analysis = _base_cf_analysis()
    mock_client = _make_cf_mock_client(analysis)

    received_snapshot = {}

    async def _capture_pipeline(*args, **kwargs):
        received_snapshot.update(kwargs.get("current_lead_data", {}))
        return DataCorrectionsAxis(corrections=[])

    with (
        patch(
            "app.summarizer._get_openai_client",
            return_value=(mock_client, "gpt-4o-mini"),
        ),
        patch(
            "app.summarizer.run_data_corrections_pipeline",
            side_effect=_capture_pipeline,
        ),
    ):
        assert cf_corr_db.async_session_factory is not None
        async with cf_corr_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    # Snapshot must include both base fields and custom fields
    assert "name" in received_snapshot, "snapshot must include base 'name'"
    assert "phone" in received_snapshot, "snapshot must include base 'phone'"
    assert "car_make" in received_snapshot, "snapshot must include 'car_make' from custom fields"
    assert "car_year" in received_snapshot, "snapshot must include 'car_year' from custom fields"
    assert received_snapshot["car_make"] == "Toyota", (
        f"snapshot car_make must be 'Toyota' from custom fields, got {received_snapshot.get('car_make')!r}"
    )
    assert received_snapshot["car_year"] == "2019", (
        f"snapshot car_year must be '2019' from custom fields, got {received_snapshot.get('car_year')!r}"
    )


async def test_snapshot_includes_base_fields_when_no_custom_fields(cf_corr_db):
    """Lead with no custom fields: snapshot still has base fields (name, phone, email, age)."""
    from app.summarizer import generate_summary_and_facts
    from app.leads.service import create_lead
    from app.analysis.universal.data_corrections import DataCorrectionsAxis

    # Create a second lead with NO custom fields
    async with cf_corr_db.async_session_factory() as sess:
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Pedro Sanchez",
            phone="+5411000088",
            lead_id="cf-corr-lead-no-cf",
        )
        await sess.commit()

    from app.calls.service import create_session, add_transcript_turn
    async with cf_corr_db.async_session_factory() as sess:
        cs = await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id="cf-corr-lead-no-cf",
        )
        cs.status = "completed"
        await add_transcript_turn(sess, cs.id, "user", "Hola")
        await sess.commit()
        session_id = cs.id

    analysis = _base_cf_analysis()
    mock_client = _make_cf_mock_client(analysis)

    received_snapshot = {}

    async def _capture_pipeline(*args, **kwargs):
        received_snapshot.update(kwargs.get("current_lead_data", {}))
        return DataCorrectionsAxis(corrections=[])

    with (
        patch(
            "app.summarizer._get_openai_client",
            return_value=(mock_client, "gpt-4o-mini"),
        ),
        patch(
            "app.summarizer.run_data_corrections_pipeline",
            side_effect=_capture_pipeline,
        ),
    ):
        assert cf_corr_db.async_session_factory is not None
        async with cf_corr_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    assert "name" in received_snapshot, "base 'name' must be in snapshot"
    assert received_snapshot["name"] == "Pedro Sanchez"
    # No custom fields → car_make absent from snapshot
    assert received_snapshot.get("car_make") is None, (
        "car_make must be None in snapshot when no custom fields exist"
    )


# ---------------------------------------------------------------------------
# Tests for CorrectableField storage attribute (dual-write to custom fields)
# ---------------------------------------------------------------------------


class TestCorrectableFieldStorageAttribute:
    """Tests for the new 'storage' attribute on CorrectableField registry entries.

    Design: CorrectableField gains a 'storage' attribute:
    - 'lead_attr': write to Lead ORM column (name, phone, email)
    - 'custom_field': write to lead_custom_fields table (car_make, car_model, car_year,
      current_insurance, age)

    During transition: DUAL-WRITE — corrections write to BOTH.
    """

    def test_name_correction_uses_lead_attr_storage(self):
        """name field uses 'lead_attr' storage — writes directly to Lead ORM."""
        from app.analysis.universal.data_corrections import CORRECTABLE_FIELDS

        entry = CORRECTABLE_FIELDS["name"]
        assert entry.storage == "lead_attr", (
            f"'name' must use 'lead_attr' storage, got {entry.storage!r}"
        )

    def test_phone_correction_uses_lead_attr_storage(self):
        """phone field uses 'lead_attr' storage."""
        from app.analysis.universal.data_corrections import CORRECTABLE_FIELDS

        entry = CORRECTABLE_FIELDS["phone"]
        assert entry.storage == "lead_attr", (
            f"'phone' must use 'lead_attr' storage, got {entry.storage!r}"
        )

    def test_email_correction_uses_lead_attr_storage(self):
        """email field uses 'lead_attr' storage."""
        from app.analysis.universal.data_corrections import CORRECTABLE_FIELDS

        entry = CORRECTABLE_FIELDS["email"]
        assert entry.storage == "lead_attr", (
            f"'email' must use 'lead_attr' storage, got {entry.storage!r}"
        )

    def test_car_make_correction_uses_custom_field_storage(self):
        """car_make uses 'custom_field' storage → corrections write to lead_custom_fields."""
        from app.analysis.universal.data_corrections import CORRECTABLE_FIELDS

        entry = CORRECTABLE_FIELDS["car_make"]
        assert entry.storage == "custom_field", (
            f"'car_make' must use 'custom_field' storage, got {entry.storage!r}"
        )

    def test_car_model_correction_uses_custom_field_storage(self):
        """car_model uses 'custom_field' storage."""
        from app.analysis.universal.data_corrections import CORRECTABLE_FIELDS

        entry = CORRECTABLE_FIELDS["car_model"]
        assert entry.storage == "custom_field", (
            f"'car_model' must use 'custom_field' storage, got {entry.storage!r}"
        )

    def test_car_year_correction_uses_custom_field_storage(self):
        """car_year uses 'custom_field' storage."""
        from app.analysis.universal.data_corrections import CORRECTABLE_FIELDS

        entry = CORRECTABLE_FIELDS["car_year"]
        assert entry.storage == "custom_field", (
            f"'car_year' must use 'custom_field' storage, got {entry.storage!r}"
        )

    def test_current_insurance_correction_uses_custom_field_storage(self):
        """current_insurance uses 'custom_field' storage."""
        from app.analysis.universal.data_corrections import CORRECTABLE_FIELDS

        entry = CORRECTABLE_FIELDS["current_insurance"]
        assert entry.storage == "custom_field", (
            f"'current_insurance' must use 'custom_field' storage, got {entry.storage!r}"
        )

    def test_age_correction_uses_custom_field_storage(self):
        """age uses 'custom_field' storage (age is a business-specific field)."""
        from app.analysis.universal.data_corrections import CORRECTABLE_FIELDS

        entry = CORRECTABLE_FIELDS["age"]
        assert entry.storage == "custom_field", (
            f"'age' must use 'custom_field' storage, got {entry.storage!r}"
        )


# ---------------------------------------------------------------------------
# Integration tests: dual-write corrections to lead_custom_fields
# ---------------------------------------------------------------------------


async def test_car_make_correction_writes_to_custom_fields(cf_corr_db):
    """Correction for car_make MUST upsert to lead_custom_fields (dual-write).

    Spec §6: corrections write to lead_custom_fields via the CRUD service.
    During transition: also writes to Lead.car_make column (if it exists).
    """
    from app.summarizer import generate_summary_and_facts
    from app.leads.lead_custom_fields_service import get_all as get_custom_fields
    from app.analysis.universal.data_corrections import DataCorrectionsAxis, DataCorrection
    from sqlalchemy import select

    session_id = await _make_cf_session(
        cf_corr_db,
        turns=[("agent", "¿Qué auto tiene?"), ("user", "Tengo un Volkswagen Polo")],
    )

    analysis = _base_cf_analysis()
    mock_client = _make_cf_mock_client(analysis)

    # Correction changes car_make from Toyota → Volkswagen
    car_correction = DataCorrectionsAxis(
        corrections=[
            DataCorrection(
                field="car_make",
                current_value="Toyota",
                corrected_value="Volkswagen",
                confidence=0.95,
                evidence="Tengo un Volkswagen Polo",
                applied=True,
            )
        ]
    )

    async def _mock_pipeline(*args, **kwargs):
        return car_correction

    with (
        patch(
            "app.summarizer._get_openai_client",
            return_value=(mock_client, "gpt-4o-mini"),
        ),
        patch(
            "app.summarizer.run_data_corrections_pipeline",
            side_effect=_mock_pipeline,
        ),
    ):
        assert cf_corr_db.async_session_factory is not None
        async with cf_corr_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    # Verify: lead_custom_fields must have car_make = "Volkswagen"
    async with cf_corr_db.async_session_factory() as db:
        cf = await get_custom_fields(db, "cf-corr-lead-001", "quintana-seguros")
        assert "car_make" in cf, "car_make must exist in custom_fields after correction"
        assert cf["car_make"] == "Volkswagen", (
            f"car_make correction must write 'Volkswagen' to custom_fields, got {cf['car_make']!r}"
        )


async def test_car_year_correction_writes_to_custom_fields(cf_corr_db):
    """Correction for car_year MUST upsert to lead_custom_fields with the new value.

    Triangulation: different field (car_year) and integer type.
    """
    from app.summarizer import generate_summary_and_facts
    from app.leads.lead_custom_fields_service import get_all as get_custom_fields
    from app.analysis.universal.data_corrections import DataCorrectionsAxis, DataCorrection

    session_id = await _make_cf_session(
        cf_corr_db,
        turns=[("agent", "¿De qué año es el auto?"), ("user", "Es del 2022")],
    )

    analysis = _base_cf_analysis()
    mock_client = _make_cf_mock_client(analysis)

    year_correction = DataCorrectionsAxis(
        corrections=[
            DataCorrection(
                field="car_year",
                current_value="2019",
                corrected_value="2022",
                confidence=0.9,
                evidence="Es del 2022",
                applied=True,
            )
        ]
    )

    async def _mock_pipeline(*args, **kwargs):
        return year_correction

    with (
        patch(
            "app.summarizer._get_openai_client",
            return_value=(mock_client, "gpt-4o-mini"),
        ),
        patch(
            "app.summarizer.run_data_corrections_pipeline",
            side_effect=_mock_pipeline,
        ),
    ):
        assert cf_corr_db.async_session_factory is not None
        async with cf_corr_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with cf_corr_db.async_session_factory() as db:
        cf = await get_custom_fields(db, "cf-corr-lead-001", "quintana-seguros")
        assert "car_year" in cf, "car_year must exist in custom_fields after correction"
        assert cf["car_year"] == "2022", (
            f"car_year must be '2022' after correction, got {cf['car_year']!r}"
        )


async def test_name_correction_still_writes_to_lead_orm(cf_corr_db):
    """Correction for 'name' (base Lead field) MUST still update Lead.name ORM column.

    This verifies that lead_attr storage path still works correctly for base fields.
    """
    from app.summarizer import generate_summary_and_facts
    from app.leads.models import Lead
    from app.analysis.universal.data_corrections import DataCorrectionsAxis, DataCorrection
    from sqlalchemy import select

    session_id = await _make_cf_session(
        cf_corr_db,
        turns=[("agent", "¿Cómo se llama?"), ("user", "Me llamo María García")],
    )

    analysis = _base_cf_analysis()
    mock_client = _make_cf_mock_client(analysis)

    name_correction = DataCorrectionsAxis(
        corrections=[
            DataCorrection(
                field="name",
                current_value="Maria Garcia",
                corrected_value="María García",
                confidence=0.95,
                evidence="Me llamo María García",
                applied=True,
            )
        ]
    )

    async def _mock_pipeline(*args, **kwargs):
        return name_correction

    with (
        patch(
            "app.summarizer._get_openai_client",
            return_value=(mock_client, "gpt-4o-mini"),
        ),
        patch(
            "app.summarizer.run_data_corrections_pipeline",
            side_effect=_mock_pipeline,
        ),
    ):
        assert cf_corr_db.async_session_factory is not None
        async with cf_corr_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with cf_corr_db.async_session_factory() as db:
        result = await db.execute(select(Lead).where(Lead.id == "cf-corr-lead-001"))
        lead = result.scalar_one()
        assert lead.name == "María García", (
            f"Lead.name must be updated to 'María García', got {lead.name!r}"
        )


async def test_zona_correction_writes_to_custom_fields(cf_corr_db):
    """Correction for zona MUST upsert to lead_custom_fields with field_key='zona'.

    Blocker (fresh review): zona tests proved registry config but NOT persistence.
    This exercises the summarizer custom-field write path end-to-end and asserts
    field_key='zona' is upserted to lead_custom_fields. zona has storage='custom_field'
    and no lead_attr column, so the custom_field write is the ONLY persistence path.

    Spec: zona-data-correction — zona is a correctable field stored in lead_custom_fields.
    """
    from app.summarizer import generate_summary_and_facts
    from app.leads.lead_custom_fields_service import get_all as get_custom_fields
    from app.analysis.universal.data_corrections import DataCorrectionsAxis, DataCorrection

    session_id = await _make_cf_session(
        cf_corr_db,
        turns=[("agent", "¿De qué zona es?"), ("user", "Vivo en Palermo")],
    )

    analysis = _base_cf_analysis()
    mock_client = _make_cf_mock_client(analysis)

    zona_correction = DataCorrectionsAxis(
        corrections=[
            DataCorrection(
                field="zona",
                current_value=None,
                corrected_value="Palermo",
                confidence=0.92,
                evidence="Vivo en Palermo",
                applied=True,
            )
        ]
    )

    async def _mock_pipeline(*args, **kwargs):
        return zona_correction

    with (
        patch(
            "app.summarizer._get_openai_client",
            return_value=(mock_client, "gpt-4o-mini"),
        ),
        patch(
            "app.summarizer.run_data_corrections_pipeline",
            side_effect=_mock_pipeline,
        ),
    ):
        assert cf_corr_db.async_session_factory is not None
        async with cf_corr_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    # Verify: lead_custom_fields must have field_key 'zona' = "Palermo"
    async with cf_corr_db.async_session_factory() as db:
        cf = await get_custom_fields(db, "cf-corr-lead-001", "quintana-seguros")
        assert "zona" in cf, (
            "field_key 'zona' must be upserted to lead_custom_fields after correction"
        )
        assert cf["zona"] == "Palermo", (
            f"zona correction must write 'Palermo' to lead_custom_fields, got {cf.get('zona')!r}"
        )


async def test_zona_correction_triangulate_zona_sur(cf_corr_db):
    """Triangulation: a different zona value ('zona sur') also upserts to lead_custom_fields.

    Different input → same persistence behavior, proving the write path is not
    hardcoded to one value.
    """
    from app.summarizer import generate_summary_and_facts
    from app.leads.lead_custom_fields_service import get_all as get_custom_fields
    from app.analysis.universal.data_corrections import DataCorrectionsAxis, DataCorrection

    session_id = await _make_cf_session(
        cf_corr_db,
        turns=[("agent", "¿De qué zona?"), ("user", "Soy de zona sur")],
    )

    analysis = _base_cf_analysis()
    mock_client = _make_cf_mock_client(analysis)

    zona_correction = DataCorrectionsAxis(
        corrections=[
            DataCorrection(
                field="zona",
                current_value=None,
                corrected_value="zona sur",
                confidence=0.88,
                evidence="Soy de zona sur",
                applied=True,
            )
        ]
    )

    async def _mock_pipeline(*args, **kwargs):
        return zona_correction

    with (
        patch(
            "app.summarizer._get_openai_client",
            return_value=(mock_client, "gpt-4o-mini"),
        ),
        patch(
            "app.summarizer.run_data_corrections_pipeline",
            side_effect=_mock_pipeline,
        ),
    ):
        assert cf_corr_db.async_session_factory is not None
        async with cf_corr_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with cf_corr_db.async_session_factory() as db:
        cf = await get_custom_fields(db, "cf-corr-lead-001", "quintana-seguros")
        assert cf.get("zona") == "zona sur", (
            f"zona must be 'zona sur' in lead_custom_fields after correction, got {cf.get('zona')!r}"
        )


async def test_custom_field_correction_also_dual_writes_to_lead_orm(cf_corr_db):
    """DUAL-WRITE: car_make correction writes to BOTH lead_custom_fields AND Lead.car_make column.

    During transition, corrections must dual-write to preserve backward compat
    until WU-7 removes the legacy columns.
    """
    from app.summarizer import generate_summary_and_facts
    from app.leads.models import Lead
    from app.leads.lead_custom_fields_service import get_all as get_custom_fields
    from app.analysis.universal.data_corrections import DataCorrectionsAxis, DataCorrection
    from sqlalchemy import select

    session_id = await _make_cf_session(
        cf_corr_db,
        turns=[("agent", "¿Qué auto tiene?"), ("user", "Tengo un Fiat Cronos")],
    )

    analysis = _base_cf_analysis()
    mock_client = _make_cf_mock_client(analysis)

    correction = DataCorrectionsAxis(
        corrections=[
            DataCorrection(
                field="car_make",
                current_value="Toyota",
                corrected_value="Fiat",
                confidence=0.9,
                evidence="Tengo un Fiat Cronos",
                applied=True,
            )
        ]
    )

    async def _mock_pipeline(*args, **kwargs):
        return correction

    with (
        patch(
            "app.summarizer._get_openai_client",
            return_value=(mock_client, "gpt-4o-mini"),
        ),
        patch(
            "app.summarizer.run_data_corrections_pipeline",
            side_effect=_mock_pipeline,
        ),
    ):
        assert cf_corr_db.async_session_factory is not None
        async with cf_corr_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with cf_corr_db.async_session_factory() as db:
        # 1. custom_fields must have the new value
        cf = await get_custom_fields(db, "cf-corr-lead-001", "quintana-seguros")
        assert cf["car_make"] == "Fiat", (
            f"car_make in custom_fields must be 'Fiat', got {cf.get('car_make')!r}"
        )

        # 2. Lead ORM column must ALSO have the new value (dual-write)
        result = await db.execute(select(Lead).where(Lead.id == "cf-corr-lead-001"))
        lead = result.scalar_one()
        assert lead.car_make == "Fiat", (
            f"Lead.car_make must ALSO be 'Fiat' (dual-write), got {lead.car_make!r}"
        )
