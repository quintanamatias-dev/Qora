"""CRM Parity module — Unit tests.

Tests cover:
- SyncState.UNKNOWN returned when crm_value is None (no sync engine)
- SyncState.IN_SYNC when qora_value matches crm_value (case/whitespace insensitive)
- SyncState.OUT_OF_SYNC when qora_value differs from crm_value
- resolve_latest_correction: returns None when list is empty
- resolve_latest_correction: returns the most recent correction for a field
- resolve_latest_correction: older call correction is NOT returned when a newer one exists
- resolve_latest_correction: ignores corrections for other fields
- Multiple fields handled independently

Spec: openspec/changes/post-call-analysis-bi-friendly/specs/crm-parity/spec.md
"""

import pytest

from app.analytics.crm_parity import SyncState, resolve_sync_state, resolve_latest_correction


# ---------------------------------------------------------------------------
# SyncState enum values
# ---------------------------------------------------------------------------

def test_sync_state_values_are_stable_english_codes() -> None:
    """SyncState string values must be stable English identifiers."""
    assert SyncState.IN_SYNC == "in_sync"
    assert SyncState.OUT_OF_SYNC == "out_of_sync"
    assert SyncState.UNKNOWN == "unknown"


# ---------------------------------------------------------------------------
# resolve_sync_state — UNKNOWN when no CRM value
# ---------------------------------------------------------------------------

def test_resolve_sync_state_unknown_when_crm_value_is_none() -> None:
    """Spec scenario: CRM value not available → result is unknown."""
    result = resolve_sync_state(field="zona", qora_value="Palermo")
    assert result == SyncState.UNKNOWN


def test_resolve_sync_state_unknown_when_crm_value_not_provided() -> None:
    """Default crm_value=None means no sync engine is present → UNKNOWN."""
    result = resolve_sync_state(field="age", qora_value="35")
    assert result is SyncState.UNKNOWN


def test_resolve_sync_state_unknown_when_qora_value_none_and_no_crm() -> None:
    """Even when qora_value is None and no CRM, result is UNKNOWN (not a special case)."""
    result = resolve_sync_state(field="zona", qora_value=None)
    assert result == SyncState.UNKNOWN


# ---------------------------------------------------------------------------
# resolve_sync_state — IN_SYNC
# ---------------------------------------------------------------------------

def test_resolve_sync_state_in_sync_when_values_match_exactly() -> None:
    """Spec scenario: Lead has zona='Palermo', CRM has zona='Palermo' → in_sync."""
    result = resolve_sync_state(field="zona", qora_value="Palermo", crm_value="Palermo")
    assert result == SyncState.IN_SYNC


def test_resolve_sync_state_in_sync_case_insensitive() -> None:
    """String comparison is case-insensitive: 'PALERMO' == 'palermo'."""
    result = resolve_sync_state(field="zona", qora_value="PALERMO", crm_value="palermo")
    assert result == SyncState.IN_SYNC


def test_resolve_sync_state_in_sync_whitespace_stripped() -> None:
    """Leading/trailing whitespace is stripped before comparison."""
    result = resolve_sync_state(field="zona", qora_value="  Palermo  ", crm_value="Palermo")
    assert result == SyncState.IN_SYNC


# ---------------------------------------------------------------------------
# resolve_sync_state — OUT_OF_SYNC
# ---------------------------------------------------------------------------

def test_resolve_sync_state_out_of_sync_when_values_differ() -> None:
    """Spec scenario: qora=Belgrano, CRM=Palermo → out_of_sync."""
    result = resolve_sync_state(field="zona", qora_value="Belgrano", crm_value="Palermo")
    assert result == SyncState.OUT_OF_SYNC


def test_resolve_sync_state_out_of_sync_for_different_field() -> None:
    """OUT_OF_SYNC works for any field, not just zona."""
    result = resolve_sync_state(field="age", qora_value="30", crm_value="35")
    assert result == SyncState.OUT_OF_SYNC


# ---------------------------------------------------------------------------
# resolve_latest_correction — recency lookup
# ---------------------------------------------------------------------------

def test_resolve_latest_correction_returns_none_for_empty_list() -> None:
    """No corrections → return None."""
    result = resolve_latest_correction(corrections_by_call=[], field="zona")
    assert result is None


def test_resolve_latest_correction_returns_the_single_correction_when_only_one() -> None:
    """Single correction for the field → return it."""
    correction = {
        "call_timestamp": "2026-01-10T10:00:00Z",
        "field": "zona",
        "corrected_value": "Palermo",
        "applied_to_qora": True,
    }
    result = resolve_latest_correction(corrections_by_call=[correction], field="zona")
    assert result is not None
    assert result["corrected_value"] == "Palermo"


def test_resolve_latest_correction_returns_most_recent_when_multiple() -> None:
    """Spec scenario: call #2 correction supersedes call #1 for the same field."""
    older = {
        "call_timestamp": "2026-01-10T10:00:00Z",
        "field": "zona",
        "corrected_value": "Palermo",
        "applied_to_qora": True,
    }
    newer = {
        "call_timestamp": "2026-01-15T14:00:00Z",
        "field": "zona",
        "corrected_value": "Belgrano",
        "applied_to_qora": True,
    }
    result = resolve_latest_correction(corrections_by_call=[older, newer], field="zona")
    assert result is not None
    assert result["corrected_value"] == "Belgrano"


def test_resolve_latest_correction_order_independent() -> None:
    """Sorting is by timestamp, not by list position."""
    newer = {
        "call_timestamp": "2026-01-15T14:00:00Z",
        "field": "zona",
        "corrected_value": "Belgrano",
        "applied_to_qora": True,
    }
    older = {
        "call_timestamp": "2026-01-10T10:00:00Z",
        "field": "zona",
        "corrected_value": "Palermo",
        "applied_to_qora": True,
    }
    # newer listed first in input — result must still be the newest by timestamp
    result = resolve_latest_correction(corrections_by_call=[newer, older], field="zona")
    assert result is not None
    assert result["corrected_value"] == "Belgrano"


def test_resolve_latest_correction_ignores_corrections_for_other_fields() -> None:
    """Only corrections for the requested field are considered."""
    zona_correction = {
        "call_timestamp": "2026-01-10T10:00:00Z",
        "field": "zona",
        "corrected_value": "Palermo",
        "applied_to_qora": True,
    }
    age_correction = {
        "call_timestamp": "2026-01-15T14:00:00Z",  # newer but different field
        "field": "age",
        "corrected_value": "32",
        "applied_to_qora": True,
    }
    result = resolve_latest_correction(
        corrections_by_call=[zona_correction, age_correction],
        field="zona",
    )
    assert result is not None
    assert result["corrected_value"] == "Palermo"


def test_resolve_latest_correction_returns_none_when_field_not_in_list() -> None:
    """Field not present in any correction → return None."""
    correction = {
        "call_timestamp": "2026-01-10T10:00:00Z",
        "field": "age",
        "corrected_value": "28",
        "applied_to_qora": True,
    }
    result = resolve_latest_correction(corrections_by_call=[correction], field="zona")
    assert result is None
