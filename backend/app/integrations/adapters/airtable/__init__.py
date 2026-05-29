"""Airtable CRM adapter package.

Re-exports the public surface so callers keep importing from
``app.integrations.adapters.airtable`` regardless of internal file layout.
"""

from app.integrations.adapters.airtable.adapter import (
    AirtableAdapter,
    AirtableUpsertError,
    make_adapter,
)

__all__ = ["AirtableAdapter", "AirtableUpsertError", "make_adapter"]
