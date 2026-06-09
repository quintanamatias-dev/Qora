"""WU-7 Cleanup tests — dynamic-lead-fields.

RED tests for:
- 7.1a: seed_leads() creates custom_fields rows (not just legacy columns)
- 7.1b: _apply_data_corrections (legacy string parser) removed from summarizer
- 7.1c: get_lead_details returns custom_fields key
- 7.1d: _is_quote_ready_legacy not called when custom_fields available
- AC-1: no production imports of register_interest anywhere in app/
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import SecretStr
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Fixture: seeded DB
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_db(tmp_path: Path):
    """DB with Quintana + 5 seed leads for WU-7 tests."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/wu7_test.db",
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
# 7.1a — seed_leads creates custom_fields rows
# ---------------------------------------------------------------------------


class TestSeedLeadsCustomFields:
    """WU-7 7.1a: seed_leads must NOT pass car_make/car_model/car_year/current_insurance
    to the Lead constructor. Instead, it must create lead_custom_fields rows for those
    fields after the lead is created.
    """

    async def test_seed_leads_populates_car_make_custom_field(self, seeded_db):
        """seed_leads() creates a custom_fields row for car_make on lead-quintana-001.

        GIVEN seed_leads() runs
        WHEN lead-quintana-001 is seeded with car_make='Toyota'
        THEN a lead_custom_fields row exists for (lead-quintana-001, quintana-seguros, car_make)
        AND field_value == 'Toyota'
        """
        from app.leads.lead_custom_fields_service import get_all

        async with seeded_db.async_session_factory() as sess:
            custom_fields = await get_all(sess, "lead-quintana-001", "quintana-seguros")

        assert "car_make" in custom_fields, (
            f"car_make must be in custom_fields after seed. Got: {list(custom_fields)}"
        )
        assert custom_fields["car_make"] == "Toyota", (
            f"car_make must be 'Toyota'. Got: {custom_fields['car_make']}"
        )

    async def test_seed_leads_populates_car_model_and_year_custom_fields(self, seeded_db):
        """seed_leads() creates custom_fields rows for car_model and car_year.

        GIVEN seed_leads() runs
        WHEN lead-quintana-001 is seeded with car_model='Corolla', car_year=2021
        THEN lead_custom_fields has car_model='Corolla' and car_year='2021'
        """
        from app.leads.lead_custom_fields_service import get_all

        async with seeded_db.async_session_factory() as sess:
            custom_fields = await get_all(sess, "lead-quintana-001", "quintana-seguros")

        assert "car_model" in custom_fields, (
            f"car_model must be in custom_fields. Got: {list(custom_fields)}"
        )
        assert custom_fields["car_model"] == "Corolla"

        assert "car_year" in custom_fields, (
            f"car_year must be in custom_fields. Got: {list(custom_fields)}"
        )
        assert custom_fields["car_year"] == "2021"  # stored as TEXT

    async def test_seed_leads_populates_current_insurance_custom_field(self, seeded_db):
        """seed_leads() creates custom_fields row for current_insurance when present.

        GIVEN lead-quintana-005 has current_insurance='La Caja'
        WHEN seed_leads() runs
        THEN a custom_fields row exists with field_key='current_insurance', field_value='La Caja'
        """
        from app.leads.lead_custom_fields_service import get_all

        async with seeded_db.async_session_factory() as sess:
            custom_fields = await get_all(sess, "lead-quintana-005", "quintana-seguros")

        assert "current_insurance" in custom_fields, (
            f"current_insurance must be in custom_fields. Got: {list(custom_fields)}"
        )
        assert custom_fields["current_insurance"] == "La Caja"

    async def test_seed_leads_no_custom_field_for_null_insurance(self, seeded_db):
        """seed_leads() does NOT create custom_fields row when current_insurance is None.

        GIVEN lead-quintana-001 has current_insurance=None
        WHEN seed_leads() runs
        THEN no custom_fields row for 'current_insurance' exists for lead-001
        """
        from app.leads.lead_custom_fields_service import get_all

        async with seeded_db.async_session_factory() as sess:
            custom_fields = await get_all(sess, "lead-quintana-001", "quintana-seguros")

        # car_make should exist, current_insurance should NOT (it's None)
        assert "current_insurance" not in custom_fields, (
            "current_insurance must NOT be in custom_fields when seed value is None. "
            f"Got: {custom_fields}"
        )


# ---------------------------------------------------------------------------
# 7.1b — _apply_data_corrections (legacy string parser) must be removed
# ---------------------------------------------------------------------------


class TestLegacyApplyDataCorrectionsRemoved:
    """WU-7 7.1b: _apply_data_corrections (old string-parsing function) must be removed.

    The STRUCTURED corrections pipeline (_apply_structured_corrections) remains.
    Only the legacy free-text line-parser must be gone.
    """

    def test_legacy_apply_data_corrections_not_importable(self):
        """_apply_data_corrections must not exist in app.summarizer after WU-7.

        GIVEN summarizer.py has been cleaned up
        WHEN importing _apply_data_corrections from app.summarizer
        THEN ImportError is raised (the function is gone)
        """
        import app.summarizer as summarizer_module

        assert not hasattr(summarizer_module, "_apply_data_corrections"), (
            "_apply_data_corrections (legacy string parser) must be removed from summarizer.py. "
            "The structured corrections pipeline (_apply_structured_corrections) remains."
        )

    def test_structured_corrections_still_present(self):
        """_apply_structured_corrections must still exist (not removed).

        Only the old string-parser is removed; the structured pipeline stays.
        """
        import app.summarizer as summarizer_module

        assert hasattr(summarizer_module, "_apply_structured_corrections"), (
            "_apply_structured_corrections must still exist in summarizer.py. "
            "Only the legacy _apply_data_corrections string parser is removed."
        )

    def test_is_quote_ready_legacy_removed(self):
        """_is_quote_ready_legacy must be removed after WU-7.

        The legacy fallback using lead.car_make/car_model/car_year/age/zona
        must no longer exist. Only the custom_fields path is used.
        """
        import app.summarizer as summarizer_module

        assert not hasattr(summarizer_module, "_is_quote_ready_legacy"), (
            "_is_quote_ready_legacy must be removed from summarizer.py. "
            "apply_status_from_next_action must use only the custom_fields path."
        )


# ---------------------------------------------------------------------------
# 7.1c — get_lead_details returns custom_fields
# ---------------------------------------------------------------------------


class TestGetLeadDetailsCustomFields:
    """WU-7 7.1c: get_lead_details must return a custom_fields key in its response.

    Previously, the tool only returned legacy Lead ORM columns (car_make, etc.).
    After WU-7, it must also load and return custom fields from lead_custom_fields.
    """

    async def test_get_lead_details_returns_custom_fields_key(self, seeded_db):
        """get_lead_details response must include 'custom_fields' key.

        GIVEN a seeded lead with car_make custom field
        WHEN get_lead_details is called
        THEN result contains 'custom_fields' key with a dict
        """
        from app.tools.get_lead_details import get_lead_details

        async with seeded_db.async_session_factory() as sess:
            result = await get_lead_details(
                session=sess,
                lead_id="lead-quintana-001",
                client_id="quintana-seguros",
            )

        assert "custom_fields" in result, (
            f"get_lead_details must return 'custom_fields'. Got keys: {list(result)}"
        )
        assert isinstance(result["custom_fields"], dict), (
            f"custom_fields must be a dict. Got: {type(result['custom_fields'])}"
        )

    async def test_get_lead_details_custom_fields_contains_seeded_car_data(self, seeded_db):
        """get_lead_details custom_fields must contain the seeded car fields.

        GIVEN seed has created custom_fields rows for lead-quintana-001
        WHEN get_lead_details is called with client_id='quintana-seguros'
        THEN custom_fields['car_make'] == 'Toyota'
        """
        from app.tools.get_lead_details import get_lead_details

        async with seeded_db.async_session_factory() as sess:
            result = await get_lead_details(
                session=sess,
                lead_id="lead-quintana-001",
                client_id="quintana-seguros",
            )

        cf = result.get("custom_fields", {})
        assert cf.get("car_make") == "Toyota", (
            f"custom_fields['car_make'] must be 'Toyota'. Got: {cf}"
        )

    async def test_get_lead_details_without_client_id_returns_empty_custom_fields(self, seeded_db):
        """get_lead_details without client_id returns empty custom_fields (not an error).

        Backward compat: callers that don't pass client_id get an empty dict,
        not a crash.
        """
        from app.tools.get_lead_details import get_lead_details

        async with seeded_db.async_session_factory() as sess:
            result = await get_lead_details(
                session=sess,
                lead_id="lead-quintana-001",
            )

        # Must not crash and must have custom_fields key (empty)
        assert "custom_fields" in result, (
            "get_lead_details must always include 'custom_fields' key, even without client_id"
        )
        # Without client_id, isolation means we return empty
        assert isinstance(result["custom_fields"], dict)


# ---------------------------------------------------------------------------
# AC-1: No active production code reads legacy columns
# ---------------------------------------------------------------------------


class TestNoLegacyColumnReadsInProductionCode:
    """AC-1: After WU-7, no production code in app/ reads lead.car_make,
    lead.car_model, lead.car_year, lead.current_insurance, lead.age, lead.zona
    in active execution paths (static analysis check).
    """

    def test_webhook_contexto_block_does_not_read_lead_car_make_directly(self):
        """webhook.py [CONTEXTO DEL LEAD] block must NOT read lead.car_make directly.

        After WU-7, the webhook reads car data from custom_fields loaded from DB,
        not from Lead ORM attributes directly in the string format line.
        """
        webhook_path = Path(__file__).parent.parent.parent / "app" / "voice" / "webhook.py"
        source = webhook_path.read_text(encoding="utf-8")

        # Find the LAST occurrence of [CONTEXTO DEL LEAD] — that's the actual f-string block,
        # not the comment/docstring that appears earlier in the file.
        last_idx = 0
        idx = source.find("[CONTEXTO DEL LEAD]")
        while idx != -1:
            last_idx = idx
            idx = source.find("[CONTEXTO DEL LEAD]", idx + 1)

        assert last_idx > 0, "[CONTEXTO DEL LEAD] block must still exist in webhook.py"

        # Get the ~400 chars after the CONTEXTO marker (covers the f-string block)
        snippet = source[last_idx : last_idx + 400]

        assert "lead.car_make" not in snippet, (
            "webhook.py [CONTEXTO DEL LEAD] block must NOT read lead.car_make directly. "
            "It must use custom_fields loaded from DB instead.\n"
            f"Offending snippet: {snippet!r}"
        )
        assert "lead.car_model" not in snippet, (
            "webhook.py [CONTEXTO DEL LEAD] block must NOT read lead.car_model directly."
        )
        assert "lead.car_year" not in snippet, (
            "webhook.py [CONTEXTO DEL LEAD] block must NOT read lead.car_year directly."
        )
        assert "lead.current_insurance" not in snippet, (
            "webhook.py [CONTEXTO DEL LEAD] block must NOT read lead.current_insurance directly."
        )

    def test_register_interest_not_imported_in_app(self):
        """No file in app/ imports register_interest.

        AC-6: register_interest must be fully gone from production code.
        """
        app_dir = Path(__file__).parent.parent.parent / "app"
        py_files = list(app_dir.rglob("*.py"))
        assert py_files, "No .py files found in app/ — check path"

        offending = []
        for f in py_files:
            content = f.read_text(encoding="utf-8")
            # Check for active imports (not comments)
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "register_interest" in stripped and "import" in stripped:
                    offending.append(f"{f.name}:{stripped}")

        assert not offending, (
            "No app/ file may import register_interest after WU-7. "
            f"Found offending imports: {offending}"
        )
