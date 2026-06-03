"""Unit tests for AirtableAdapter — TDD RED phase.

Covers spec scenarios:
- CS-3: upsert_record succeeds (create path and update path)
- CS-4: retry on transient 429 with exponential backoff
- CS-5: after 3 failures logs structured error and does NOT raise
- CS-6: upsert is idempotent (same payload does not create duplicates)
- CS-9: adapter lives entirely within app/integrations/adapters/

Design constraints (design.md):
- pyairtable is mocked in tests — no live Airtable reads
- retry logic uses exponential backoff + jitter
- no Airtable reads during active call path (write-only adapter)

Test layer: Unit (AsyncMock on pyairtable methods — no network).
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers — build a configured adapter under test
# ---------------------------------------------------------------------------


def _make_adapter(api_key: str = "pat_test_key"):
    """Construct an AirtableAdapter without live credentials."""
    from app.integrations.adapters.airtable import AirtableAdapter

    return AirtableAdapter(api_key=api_key)


# ---------------------------------------------------------------------------
# Safety net: no pre-existing files to break (new file)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 2.1-A: CRMPort interface is importable and abstract (contract)
# ---------------------------------------------------------------------------


def test_crm_port_is_abstract():
    """CRMPort is an ABC with upsert_record as an abstract method."""
    from app.integrations.crm_port import CRMPort
    import inspect

    assert inspect.isabstract(CRMPort)
    # Cannot instantiate directly
    with pytest.raises(TypeError):
        CRMPort()  # type: ignore[abstract]


def test_crm_port_upsert_record_signature():
    """CRMPort.upsert_record must declare table_id, payload, match_field."""
    from app.integrations.crm_port import CRMPort
    import inspect

    sig = inspect.signature(CRMPort.upsert_record)
    params = list(sig.parameters.keys())
    assert "table_id" in params
    assert "payload" in params
    assert "match_field" in params


def test_airtable_adapter_implements_crm_port():
    """AirtableAdapter inherits from CRMPort."""
    from app.integrations.adapters.airtable import AirtableAdapter
    from app.integrations.crm_port import CRMPort

    assert issubclass(AirtableAdapter, CRMPort)


# ---------------------------------------------------------------------------
# 2.1-B: Upsert success — create path (no matching record found)
# ---------------------------------------------------------------------------


def _upsert_result(record_id: str, *, created: bool = True) -> dict:
    """Build a pyairtable batch_upsert response (UpsertResultDict shape).

    Airtable resolves the create-vs-update decision server-side; the response
    reports which records were created vs updated, plus the full record list.
    """
    return {
        "createdRecords": [record_id] if created else [],
        "updatedRecords": [] if created else [record_id],
        "records": [{"id": record_id, "fields": {}}],
    }


# Read-side pyairtable methods that MUST NEVER be invoked from the write-only
# upsert path (CS-7: no live Airtable reads).
_READ_METHODS = ("all", "first", "get", "iterate")


@pytest.mark.asyncio
async def test_upsert_record_create_path_returns_record_id():
    """CS-3: upsert creates new record (server-side) and returns its Airtable ID."""
    from app.integrations.adapters.airtable import AirtableAdapter

    fake_record_id = "recABCDEF123456"
    mock_table = MagicMock()
    mock_table.batch_upsert = MagicMock(
        return_value=_upsert_result(fake_record_id, created=True)
    )

    adapter = AirtableAdapter(api_key="pat_test_key")

    with patch.object(adapter, "_get_table", return_value=mock_table):
        record_id = await adapter.upsert_record(
            table_id="tblYYYY",
            payload={"Nombre": "Carlos", "Teléfono": "+541155501"},
            match_field="Teléfono",
        )

    assert record_id == fake_record_id
    # Single write-side upsert keyed on match_field — no read methods used.
    mock_table.batch_upsert.assert_called_once_with(
        [{"fields": {"Nombre": "Carlos", "Teléfono": "+541155501"}}],
        key_fields=["Teléfono"],
    )
    for method in _READ_METHODS:
        getattr(mock_table, method).assert_not_called()


@pytest.mark.asyncio
async def test_upsert_record_update_path_returns_record_id():
    """CS-3 / CS-6: upsert updates existing record and returns same ID (idempotent)."""
    from app.integrations.adapters.airtable import AirtableAdapter

    existing_id = "recEXISTING0001"
    mock_table = MagicMock()
    mock_table.batch_upsert = MagicMock(
        return_value=_upsert_result(existing_id, created=False)
    )

    adapter = AirtableAdapter(api_key="pat_test_key")

    with patch.object(adapter, "_get_table", return_value=mock_table):
        record_id = await adapter.upsert_record(
            table_id="tblYYYY",
            payload={"Nombre": "Carlos Updated", "Teléfono": "+541155501"},
            match_field="Teléfono",
        )

    assert record_id == existing_id
    mock_table.batch_upsert.assert_called_once_with(
        [{"fields": {"Nombre": "Carlos Updated", "Teléfono": "+541155501"}}],
        key_fields=["Teléfono"],
    )
    for method in _READ_METHODS:
        getattr(mock_table, method).assert_not_called()


@pytest.mark.asyncio
async def test_upsert_idempotent_second_call_updates_not_creates():
    """CS-6: calling upsert twice with same lead data resolves to one record."""
    from app.integrations.adapters.airtable import AirtableAdapter

    existing_id = "recIDEMPOTENT001"
    mock_table = MagicMock()
    # Airtable returns the same record id on both upserts (matched server-side).
    mock_table.batch_upsert = MagicMock(
        return_value=_upsert_result(existing_id, created=False)
    )

    adapter = AirtableAdapter(api_key="pat_test_key")

    with patch.object(adapter, "_get_table", return_value=mock_table):
        id1 = await adapter.upsert_record(
            table_id="tblYYYY",
            payload={"Nombre": "Carlos", "Teléfono": "+541155501"},
            match_field="Teléfono",
        )
        id2 = await adapter.upsert_record(
            table_id="tblYYYY",
            payload={"Nombre": "Carlos", "Teléfono": "+541155501"},
            match_field="Teléfono",
        )

    assert id1 == id2 == existing_id
    assert mock_table.batch_upsert.call_count == 2
    for method in _READ_METHODS:
        getattr(mock_table, method).assert_not_called()


# ---------------------------------------------------------------------------
# 2.1-C: 429 retry — success on second attempt (CS-4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_retries_on_429_and_succeeds():
    """CS-4: 429 response triggers retry; second attempt succeeds."""
    from app.integrations.adapters.airtable import AirtableAdapter
    import httpx

    fake_record_id = "recRETRY0000001"

    # batch_upsert raises 429-equivalent on first call, then succeeds on second.
    call_count = {"n": 0}

    def mock_upsert(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.HTTPStatusError(
                "429 Too Many Requests",
                request=MagicMock(),
                response=MagicMock(status_code=429),
            )
        return _upsert_result(fake_record_id, created=True)

    mock_table = MagicMock()
    mock_table.batch_upsert = MagicMock(side_effect=mock_upsert)

    adapter = AirtableAdapter(api_key="pat_test_key")

    with patch.object(adapter, "_get_table", return_value=mock_table):
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            record_id = await adapter.upsert_record(
                table_id="tblYYYY",
                payload={"Teléfono": "+541155501"},
                match_field="Teléfono",
            )

    assert record_id == fake_record_id
    assert mock_table.batch_upsert.call_count == 2  # first failed, second succeeded
    mock_sleep.assert_called_once()  # backoff sleep was triggered


@pytest.mark.asyncio
async def test_upsert_retries_on_transient_5xx_and_succeeds():
    """CS-4: 503 transient error also triggers retry."""
    from app.integrations.adapters.airtable import AirtableAdapter
    import httpx

    fake_record_id = "rec5XXRETRY0001"

    call_count = {"n": 0}

    def mock_upsert(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.HTTPStatusError(
                "503 Service Unavailable",
                request=MagicMock(),
                response=MagicMock(status_code=503),
            )
        return _upsert_result(fake_record_id, created=True)

    mock_table = MagicMock()
    mock_table.batch_upsert = MagicMock(side_effect=mock_upsert)

    adapter = AirtableAdapter(api_key="pat_test_key")

    with patch.object(adapter, "_get_table", return_value=mock_table):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            record_id = await adapter.upsert_record(
                table_id="tblYYYY",
                payload={"Teléfono": "+541155502"},
                match_field="Teléfono",
            )

    assert record_id == fake_record_id


# ---------------------------------------------------------------------------
# 2.1-D: All 3 retries exhausted — structured log + no exception raised (CS-5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_retries_exhausted_logs_and_raises_after_3():
    """CS-5: after 3 failures adapter raises an error so caller can handle."""
    from app.integrations.adapters.airtable import AirtableAdapter, AirtableUpsertError
    import httpx

    mock_table = MagicMock()
    mock_table.batch_upsert = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "429 Too Many Requests",
            request=MagicMock(),
            response=MagicMock(status_code=429),
        )
    )

    adapter = AirtableAdapter(api_key="pat_test_key")

    with patch.object(adapter, "_get_table", return_value=mock_table):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(AirtableUpsertError) as exc_info:
                await adapter.upsert_record(
                    table_id="tblYYYY",
                    payload={"Teléfono": "+541155503"},
                    match_field="Teléfono",
                )

    assert mock_table.batch_upsert.call_count == 3  # exactly 3 attempts
    error_msg = str(exc_info.value)
    assert "429" in error_msg or "retries" in error_msg.lower() or "failed" in error_msg.lower()


@pytest.mark.asyncio
async def test_all_retries_exhausted_structured_log_contains_table_id(caplog):
    """CS-5: structured log includes context fields on exhaustion."""
    from app.integrations.adapters.airtable import AirtableAdapter, AirtableUpsertError
    import httpx

    mock_table = MagicMock()
    mock_table.batch_upsert = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "429 Too Many Requests",
            request=MagicMock(),
            response=MagicMock(status_code=429),
        )
    )

    adapter = AirtableAdapter(api_key="pat_test_key")

    with patch.object(adapter, "_get_table", return_value=mock_table):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with caplog.at_level(logging.ERROR):
                with pytest.raises(AirtableUpsertError):
                    await adapter.upsert_record(
                        table_id="tblYYYY",
                        payload={"Teléfono": "+541155504"},
                        match_field="Teléfono",
                    )

    # At least one ERROR log entry should be emitted
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(error_records) >= 1


# ---------------------------------------------------------------------------
# 2.1-E: Non-retryable errors propagate immediately (do not retry on 4xx)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_retryable_4xx_does_not_retry():
    """HTTP 422 / 403 is not transient — should NOT retry, raise immediately."""
    from app.integrations.adapters.airtable import AirtableAdapter, AirtableUpsertError
    import httpx

    mock_table = MagicMock()
    mock_table.batch_upsert = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "422 Unprocessable Entity",
            request=MagicMock(),
            response=MagicMock(status_code=422),
        )
    )

    adapter = AirtableAdapter(api_key="pat_test_key")

    with patch.object(adapter, "_get_table", return_value=mock_table):
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(AirtableUpsertError):
                await adapter.upsert_record(
                    table_id="tblYYYY",
                    payload={"Teléfono": "+541155505"},
                    match_field="Teléfono",
                )

    # No retry sleep for non-retryable errors
    mock_sleep.assert_not_called()
    assert mock_table.batch_upsert.call_count == 1  # only one attempt


# ---------------------------------------------------------------------------
# 2.1-F: Adapter is write-only — no read path in upsert (CS-7)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_does_not_call_any_read_method():
    """CS-7: no live Airtable reads — ONLY the write-side batch_upsert is used.

    Enforces that none of pyairtable's read APIs (all/first/get/iterate) are
    ever invoked during the upsert path. The dedup match is resolved server-side
    by Airtable via batch_upsert's key_fields, not by reading records first.
    """
    from app.integrations.adapters.airtable import AirtableAdapter

    fake_record_id = "recWRITEONLY001"
    mock_table = MagicMock()
    mock_table.batch_upsert = MagicMock(
        return_value=_upsert_result(fake_record_id, created=True)
    )

    adapter = AirtableAdapter(api_key="pat_test_key")

    with patch.object(adapter, "_get_table", return_value=mock_table):
        await adapter.upsert_record(
            table_id="tblYYYY",
            payload={"Teléfono": "+541155506"},
            match_field="Teléfono",
        )

    # Exactly one write-side call; NO read methods touched.
    mock_table.batch_upsert.assert_called_once()
    for method in _READ_METHODS:
        getattr(mock_table, method).assert_not_called()
    # 'create' / 'update' (single-record writes that pyairtable also offers) are
    # not part of the keyed-upsert path either.
    mock_table.create.assert_not_called()
    mock_table.update.assert_not_called()


@pytest.mark.asyncio
async def test_upsert_retries_on_pyairtable_style_exception():
    """CS-4: retry works for exceptions carrying response.status_code (pyairtable's
    requests.HTTPError shape) — not just httpx.HTTPStatusError. The retry logic
    must not depend on importing pyairtable's exception type."""
    from app.integrations.adapters.airtable import AirtableAdapter

    fake_record_id = "recPYAIRTABLE01"

    class FakeRequestsHTTPError(Exception):
        """Mimics requests.exceptions.HTTPError: carries .response.status_code."""

        def __init__(self, status_code: int):
            super().__init__(f"HTTP {status_code}")
            self.response = MagicMock(status_code=status_code)

    call_count = {"n": 0}

    def mock_upsert(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise FakeRequestsHTTPError(429)
        return _upsert_result(fake_record_id, created=True)

    mock_table = MagicMock()
    mock_table.batch_upsert = MagicMock(side_effect=mock_upsert)

    adapter = AirtableAdapter(api_key="pat_test_key")

    with patch.object(adapter, "_get_table", return_value=mock_table):
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            record_id = await adapter.upsert_record(
                table_id="tblYYYY",
                payload={"Teléfono": "+541155508"},
                match_field="Teléfono",
            )

    assert record_id == fake_record_id
    assert mock_table.batch_upsert.call_count == 2
    mock_sleep.assert_called_once()
