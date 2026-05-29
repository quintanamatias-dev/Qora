"""Airtable CRM adapter — implements CRMPort via pyairtable.

Design decisions (design.md):
- Write-only: upsert_record is the only operation exposed to the call path (CS-7)
- Idempotent: match by `match_field` value via Airtable's write-side upsert (CS-3/CS-6)
- No live reads: uses pyairtable `Table.batch_upsert(key_fields=...)`, which is a single
  write request (POST with performUpsert). No list/all/find/get reads in the call path (CS-7)
- Retry: 3 attempts with exponential backoff + jitter on 429 / 5xx (CS-4)
- After 3 failures: log structured error and raise AirtableUpsertError (CS-5)
- Non-retryable 4xx (403, 422, etc.) fail immediately without retry
- Blocking pyairtable network calls are dispatched via asyncio.to_thread so the event
  loop is never blocked (sync HTTP under the hood).
- pyairtable Table is constructed lazily per call; no connection held
- asyncio.sleep used for backoff: deterministic in tests via AsyncMock patching
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from app.integrations.crm_port import CRMPort

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_ATTEMPTS = 3
_BASE_BACKOFF_SECONDS = 1.0
_MAX_BACKOFF_SECONDS = 30.0

# HTTP status codes that warrant a retry (transient)
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def _extract_status_code(exc: Exception) -> int | None:
    """Best-effort extraction of an HTTP status code from a transport exception.

    pyairtable raises ``requests.exceptions.HTTPError`` (which carries
    ``exc.response.status_code``), while tests and some transports use
    ``httpx.HTTPStatusError`` (same shape). Some libraries expose a bare
    ``exc.status_code``. This helper stays decoupled from any specific HTTP
    client so retry logic does not depend on importing pyairtable's exception
    type (which may not be installed in every environment).

    Returns the integer status code, or None if the exception is not an
    HTTP-status-bearing error.
    """
    response = getattr(exc, "response", None)
    if response is not None:
        status = getattr(response, "status_code", None)
        if isinstance(status, int):
            return status
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    return None


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class AirtableUpsertError(Exception):
    """Raised when all retry attempts for an Airtable upsert are exhausted,
    or when a non-retryable error occurs during the upsert operation.

    The message includes the table_id and failure reason for structured logging.
    """


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class AirtableAdapter(CRMPort):
    """Write-only CRM adapter backed by Airtable.

    Implements CRMPort.upsert_record() with:
    - Field-based match for idempotent upserts (no duplicate creation)
    - Exponential backoff + jitter for 429/5xx transient errors
    - Structured error logging after all retries exhausted

    Usage (via crm_sync_service — never instantiated directly from call path):
        adapter = AirtableAdapter(api_key=config.resolve_api_key())
        record_id = await adapter.upsert_record(
            table_id=config.table_id,
            payload=mapped_payload,
            match_field=config.match_field,
        )
    """

    def __init__(self, api_key: str, base_id: str = "") -> None:
        """Construct an adapter with the given Airtable Personal Access Token.

        Args:
            api_key: Airtable PAT (Personal Access Token). Never logged or stored
                     beyond this object's lifetime.
            base_id: Airtable base ID (e.g. "appXXXXXXXXXXXXXX"). Required for
                     production use; may be omitted in tests that patch _get_table.
        """
        self._api_key = api_key
        self._base_id = base_id

    def _get_table(self, table_id: str) -> Any:
        """Construct a pyairtable Table object for the given table.

        Extracted as a method so tests can patch it without touching pyairtable.
        In production, pyairtable is imported here; in tests, this method is
        patched via patch.object(adapter, '_get_table', return_value=mock_table).

        Note: pyairtable Table is constructed per-operation (no persistent connection).
        """
        try:
            from pyairtable import Table  # type: ignore[import]

            return Table(self._api_key, self._base_id, table_id)
        except ImportError as exc:
            raise ImportError(
                "pyairtable is required for AirtableAdapter. "
                "Install it: pip install pyairtable"
            ) from exc

    async def upsert_record(
        self,
        table_id: str,
        payload: dict[str, Any],
        match_field: str,
    ) -> str:
        """Upsert a record into Airtable by matching on match_field.

        Algorithm:
        1. Issue a single Airtable write-side upsert keyed on match_field
           (no read/list/find/get — the match happens server-side)
        2. Airtable updates the matching record or creates a new one (idempotent)
        3. Retry up to _MAX_ATTEMPTS times on retryable errors (429/5xx)
        4. After exhaustion: log structured error and raise AirtableUpsertError

        Args:
            table_id: Airtable table ID (e.g. "tblYYYYYYYYYYYYYY").
            payload: Dict of CRM field names → coerced values.
            match_field: CRM field name to use for de-duplication lookup.

        Returns:
            Airtable record ID string (e.g. "recABCDEF123456").

        Raises:
            AirtableUpsertError: After exhausting retries or on non-retryable error.
        """
        last_error: Exception | None = None

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                table = self._get_table(table_id)
                return await self._do_upsert(table, payload, match_field)

            except Exception as exc:
                status_code = _extract_status_code(exc)

                if status_code is None:
                    # Not an HTTP-status error — unexpected; do not retry.
                    logger.error(
                        "Airtable upsert unexpected error",
                        extra={
                            "table_id": table_id,
                            "attempt": attempt,
                            "error": str(exc),
                        },
                    )
                    raise AirtableUpsertError(
                        f"Airtable upsert unexpected error on table {table_id!r}: {exc}"
                    ) from exc

                if status_code not in _RETRYABLE_STATUS_CODES:
                    # Non-retryable HTTP error (e.g. 403, 422): fail immediately
                    logger.error(
                        "Airtable upsert failed with non-retryable error",
                        extra={
                            "table_id": table_id,
                            "status_code": status_code,
                            "attempt": attempt,
                        },
                    )
                    raise AirtableUpsertError(
                        f"Airtable upsert failed (HTTP {status_code}) on table {table_id!r}: "
                        f"{exc}"
                    ) from exc

                # Retryable transient error (429 / 5xx)
                last_error = exc
                if attempt < _MAX_ATTEMPTS:
                    backoff = _compute_backoff(attempt)
                    logger.warning(
                        "Airtable transient error — retrying",
                        extra={
                            "table_id": table_id,
                            "status_code": status_code,
                            "attempt": attempt,
                            "backoff_seconds": backoff,
                        },
                    )
                    await asyncio.sleep(backoff)

        # All retries exhausted
        logger.error(
            "Airtable upsert failed after all retries",
            extra={
                "table_id": table_id,
                "attempts": _MAX_ATTEMPTS,
                "final_error": str(last_error),
            },
        )
        raise AirtableUpsertError(
            f"Airtable upsert failed after {_MAX_ATTEMPTS} retries on table {table_id!r}: "
            f"{last_error}"
        ) from last_error

    async def _do_upsert(
        self,
        table: Any,
        payload: dict[str, Any],
        match_field: str,
    ) -> str:
        """Perform the write-side upsert without retry logic.

        Uses pyairtable ``Table.batch_upsert(records, key_fields=[match_field])``,
        which Airtable resolves entirely server-side via a single write request
        (POST with ``performUpsert``). There is NO read/list/find/get in this
        path — the dedup match is done by Airtable, not by us (CS-7: no live reads).

        The blocking pyairtable call is dispatched to a worker thread via
        ``asyncio.to_thread`` so the async event loop is never blocked by the
        synchronous HTTP request underneath pyairtable.

        Returns:
            Airtable record ID (created or updated).
        """
        result = await asyncio.to_thread(
            table.batch_upsert,
            [{"fields": payload}],
            key_fields=[match_field],
        )
        return _extract_record_id(result)


# ---------------------------------------------------------------------------
# Adapter factory (CS-9 compliance)
# ---------------------------------------------------------------------------


def make_adapter(provider: str, api_key: str, base_id: str = "") -> CRMPort:
    """Factory function: return the correct CRMPort implementation by provider name.

    Supports: "airtable"

    Adding a new adapter requires only:
    1. Add a new file to app/integrations/adapters/
    2. Add an entry in this factory

    Args:
        provider: CRM provider name (matches CRMConfig.provider, e.g. "airtable")
        api_key: Resolved API key (already fetched from env — do not log)
        base_id: Adapter-specific base/workspace identifier (e.g. Airtable base ID)

    Returns:
        Concrete CRMPort implementation.

    Raises:
        ValueError: If provider is not supported.
    """
    if provider == "airtable":
        return AirtableAdapter(api_key=api_key, base_id=base_id)
    raise ValueError(
        f"Unsupported CRM provider {provider!r}. "
        "Add it to app/integrations/adapters/ and register it in make_adapter()."
    )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _extract_record_id(result: Any) -> str:
    """Extract the upserted Airtable record ID from a batch_upsert response.

    pyairtable's ``batch_upsert`` returns an ``UpsertResultDict`` shaped like
    ``{"createdRecords": [...], "updatedRecords": [...], "records": [{"id": ...}, ...]}``.
    Older/alternate shapes return a plain list of record dicts. This helper
    handles both and returns the single affected record's ID.

    Raises:
        AirtableUpsertError: If no record ID can be found in the response.
    """
    records: Any = None
    if isinstance(result, dict):
        records = result.get("records")
    elif isinstance(result, list):
        records = result

    if records:
        first = records[0]
        record_id = first.get("id") if isinstance(first, dict) else None
        if record_id:
            return record_id

    raise AirtableUpsertError(
        f"Airtable upsert returned no record id (response: {result!r})"
    )


def _compute_backoff(attempt: int) -> float:
    """Compute exponential backoff with full jitter for a given attempt number.

    Algorithm: min(max_backoff, base * 2^attempt) * random_uniform(0, 1)
    Pure function — deterministic given a fixed random seed (useful for tests).

    Args:
        attempt: 1-indexed attempt number (1 = first failure).

    Returns:
        Sleep duration in seconds.
    """
    cap = min(_MAX_BACKOFF_SECONDS, _BASE_BACKOFF_SECONDS * (2**attempt))
    return random.uniform(0, cap)
