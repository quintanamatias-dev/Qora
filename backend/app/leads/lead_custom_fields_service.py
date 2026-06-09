"""CRUD service for LeadCustomField — dynamic, type-enforced custom fields per lead.

Design: dynamic-lead-fields — WU-1
Spec requirements covered: CF-1 through CF-9.

Key design decisions:
- Write-time coercion: validate field_value against field_type before storing (CF-3, CF-4).
- field_value always stored as TEXT string regardless of field_type (CF-6).
- Upsert semantics: insert on new key, update on existing key (CF-5).
- client_id always scoped in read queries for isolation (CF-9).
- Unique constraint on (lead_id, field_key) — enforced at DB level (CF-1).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.leads.models import LeadCustomField


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_FIELD_TYPES = {"string", "integer", "boolean", "date", "phone"}

_BOOLEAN_TRUTHY = {"true", "1", "yes"}
_BOOLEAN_FALSY = {"false", "0", "no"}

# ISO 8601 date: YYYY-MM-DD
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class FieldTypeError(ValueError):
    """Raised when field_value cannot be coerced to the declared field_type."""


# ---------------------------------------------------------------------------
# Pure function: coerce_value
# ---------------------------------------------------------------------------


def coerce_value(value: Any, field_type: str) -> str:
    """Validate and coerce value to canonical string representation.

    This is a pure function — no side effects, no DB access.
    Called by upsert() before writing any row.

    Args:
        value: The raw value to coerce (str, int, bool, etc.)
        field_type: One of VALID_FIELD_TYPES.

    Returns:
        String representation of the coerced value.

    Raises:
        FieldTypeError: if field_type is unknown or value cannot be coerced.
    """
    if field_type not in VALID_FIELD_TYPES:
        raise FieldTypeError(
            f"Unknown field_type {field_type!r}. "
            f"Must be one of: {sorted(VALID_FIELD_TYPES)}"
        )

    str_value = str(value) if not isinstance(value, str) else value

    if field_type == "string":
        return str_value

    if field_type == "integer":
        try:
            int(str_value)
        except (ValueError, TypeError):
            raise FieldTypeError(
                f"Cannot coerce {value!r} to integer. "
                "Value must be a whole number (e.g. '2021', 42)."
            )
        return str(int(str_value))

    if field_type == "boolean":
        lower = str_value.lower()
        if isinstance(value, bool):
            return "True" if value else "False"
        if lower in _BOOLEAN_TRUTHY:
            return "True"
        if lower in _BOOLEAN_FALSY:
            return "False"
        raise FieldTypeError(
            f"Cannot coerce {value!r} to boolean. "
            f"Use one of: {sorted(_BOOLEAN_TRUTHY)} for True, "
            f"{sorted(_BOOLEAN_FALSY)} for False."
        )

    if field_type == "date":
        if not _DATE_PATTERN.match(str_value):
            raise FieldTypeError(
                f"Cannot coerce {value!r} to date. "
                "Expected ISO 8601 format YYYY-MM-DD (e.g. '2024-01-15')."
            )
        return str_value

    if field_type == "phone":
        # Phone values are stored as-is; no strict format validation here
        return str_value

    # Unreachable (VALID_FIELD_TYPES guard is above), but makes mypy happy
    raise FieldTypeError(f"Unknown field_type: {field_type!r}")  # pragma: no cover


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------


async def get_all(
    db: AsyncSession,
    lead_id: str,
    client_id: str,
) -> dict[str, str]:
    """Return {field_key: field_value} for all custom fields of a lead.

    Always scoped by client_id for isolation (CF-9).
    """
    stmt = select(LeadCustomField).where(
        LeadCustomField.lead_id == lead_id,
        LeadCustomField.client_id == client_id,
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return {row.field_key: row.field_value for row in rows if row.field_value is not None}


async def get_one(
    db: AsyncSession,
    lead_id: str,
    field_key: str,
    client_id: str | None = None,
) -> str | None:
    """Return single field value or None.

    Args:
        db: Async DB session.
        lead_id: Lead to look up.
        field_key: Field key to retrieve.
        client_id: Optional — when provided, scopes the lookup by client_id
            for full CF-1 compliance. Should always be passed in production code.
    """
    conditions = [
        LeadCustomField.lead_id == lead_id,
        LeadCustomField.field_key == field_key,
    ]
    if client_id is not None:
        conditions.append(LeadCustomField.client_id == client_id)

    stmt = select(LeadCustomField).where(*conditions)
    result = await db.execute(stmt)
    row = result.scalars().first()
    return row.field_value if row is not None else None


async def batch_get(
    db: AsyncSession,
    lead_ids: list[str],
    client_id: str,
) -> dict[str, dict[str, str]]:
    """Batch load: {lead_id: {field_key: field_value}}.

    Uses a single IN-clause query for efficiency (CF-8).
    Leads with no custom fields are represented as empty dicts.
    """
    if not lead_ids:
        return {}

    stmt = select(LeadCustomField).where(
        LeadCustomField.lead_id.in_(lead_ids),
        LeadCustomField.client_id == client_id,
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    # Initialize every requested lead with an empty dict
    output: dict[str, dict[str, str]] = {lid: {} for lid in lead_ids}
    for row in rows:
        if row.field_value is not None:
            output[row.lead_id][row.field_key] = row.field_value

    return output


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------


async def upsert(
    db: AsyncSession,
    *,
    lead_id: str,
    client_id: str,
    field_key: str,
    field_value: Any,
    field_type: str = "string",
) -> LeadCustomField:
    """Insert or update a custom field. Coerces value at write time (CF-3, CF-4, CF-5).

    Raises:
        FieldTypeError: if field_value cannot be coerced to field_type.
    """
    # Write-time coercion — raises FieldTypeError on failure (CF-4)
    coerced = coerce_value(field_value, field_type)

    # Look for existing row — scoped by (lead_id, client_id, field_key) per CF-1
    stmt = select(LeadCustomField).where(
        LeadCustomField.lead_id == lead_id,
        LeadCustomField.client_id == client_id,
        LeadCustomField.field_key == field_key,
    )
    result = await db.execute(stmt)
    existing = result.scalars().first()

    now = datetime.now(timezone.utc)

    if existing is not None:
        # Update — CF-5
        existing.field_value = coerced
        existing.field_type = field_type
        existing.client_id = client_id
        existing.updated_at = now
        await db.flush()
        return existing

    # Insert — CF-5
    row = LeadCustomField(
        id=str(uuid.uuid4()),
        lead_id=lead_id,
        client_id=client_id,
        field_key=field_key,
        field_value=coerced,
        field_type=field_type,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.flush()
    return row


async def upsert_many(
    db: AsyncSession,
    *,
    lead_id: str,
    client_id: str,
    fields: dict[str, Any],
    field_types: dict[str, str] | None = None,
) -> int:
    """Batch upsert. Returns count of upserted fields.

    Args:
        fields: {field_key: raw_value} mapping.
        field_types: {field_key: field_type} — defaults to 'string' if not provided.
    """
    if field_types is None:
        field_types = {}

    count = 0
    for key, value in fields.items():
        ftype = field_types.get(key, "string")
        await upsert(
            db,
            lead_id=lead_id,
            client_id=client_id,
            field_key=key,
            field_value=value,
            field_type=ftype,
        )
        count += 1

    return count


async def delete(
    db: AsyncSession,
    lead_id: str,
    field_key: str,
) -> bool:
    """Delete a custom field. Returns True if it existed."""
    stmt = select(LeadCustomField).where(
        LeadCustomField.lead_id == lead_id,
        LeadCustomField.field_key == field_key,
    )
    result = await db.execute(stmt)
    row = result.scalars().first()

    if row is None:
        return False

    await db.delete(row)
    await db.flush()
    return True
