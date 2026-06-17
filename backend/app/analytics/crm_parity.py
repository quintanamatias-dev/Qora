"""CRM Parity — Shared sync-state resolution module.

Implements the shared interface for both surfaces that need CRM parity:
  1. Lead-level Quote Readiness fields
  2. Call-level Data Corrections (latest correction for each field)

Design: AD-6 — shared module in analytics/ package; returns SyncState.UNKNOWN
for all fields until a real CRM sync engine is implemented. This prevents any
surface from showing a fake "synced" indicator.

Spec: openspec/changes/post-call-analysis-bi-friendly/specs/crm-parity/spec.md
"""

from __future__ import annotations

from enum import Enum


# ---------------------------------------------------------------------------
# SyncState — honest three-way states
# ---------------------------------------------------------------------------

class SyncState(str, Enum):
    """Parity state between Qora stored value and client CRM value."""

    IN_SYNC = "in_sync"
    OUT_OF_SYNC = "out_of_sync"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# resolve_sync_state — shared parity resolution
# ---------------------------------------------------------------------------

def resolve_sync_state(
    field: str,
    qora_value: str | None,
    crm_value: str | None = None,
) -> SyncState:
    """Resolve parity between a Qora stored value and a client CRM value.

    Rules:
    - crm_value is None (default) → UNKNOWN (no sync engine present yet)
    - qora and crm values match (case+whitespace insensitive) → IN_SYNC
    - qora and crm values differ → OUT_OF_SYNC

    Args:
        field: The field name being compared (for context/logging only).
        qora_value: The value stored in Qora's storage.
        crm_value: The value from the client CRM. None = not available.

    Returns:
        SyncState.UNKNOWN, SyncState.IN_SYNC, or SyncState.OUT_OF_SYNC.
    """
    # No CRM value available — parity is not trackable yet
    if crm_value is None:
        return SyncState.UNKNOWN

    # Normalize for comparison: strip whitespace, lowercase
    normalized_qora = str(qora_value).strip().lower() if qora_value is not None else ""
    normalized_crm = str(crm_value).strip().lower()

    return SyncState.IN_SYNC if normalized_qora == normalized_crm else SyncState.OUT_OF_SYNC


# ---------------------------------------------------------------------------
# resolve_latest_correction — recency lookup for call-level corrections
# ---------------------------------------------------------------------------

def resolve_latest_correction(
    corrections_by_call: list[dict],
    field: str,
) -> dict | None:
    """Return the most recent correction for a field across all calls, or None.

    Used by call-level Data Corrections surface to find which call's correction
    represents the current state for a field.

    Args:
        corrections_by_call: List of correction dicts, each containing at minimum:
            - 'field': str — the field name
            - 'call_timestamp': str — ISO 8601 timestamp of the call
            - 'corrected_value': str — the value written to Qora
            - 'applied_to_qora': bool — whether the correction was applied
        field: The field name to look up.

    Returns:
        The correction dict with the latest call_timestamp for the field, or None.
    """
    # Filter to only corrections for the requested field
    matching = [c for c in corrections_by_call if c.get("field") == field]
    if not matching:
        return None

    # Sort by call_timestamp descending — ISO 8601 strings sort lexicographically
    matching.sort(key=lambda c: c.get("call_timestamp", ""), reverse=True)
    return matching[0]
