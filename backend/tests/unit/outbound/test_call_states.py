"""Unit tests for CallStatus StrEnum, VALID_TRANSITIONS, and validate_transition().

Spec: call-state-machine — Requirements:
  - CallStatus Enum: exactly 10 values, in_call MUST NOT exist
  - Explicit Transition Table: valid transitions pass, invalid raise ValueError
  - Concurrency Guard Updated: active set must be {dialing, ringing, connected}

Design: backend/app/calls/states.py — CallStatus(StrEnum) + VALID_TRANSITIONS dict
  + validate_transition() pure function.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Task 1.1 RED: Import guard — module must exist with correct structure
# ---------------------------------------------------------------------------


def test_module_importable() -> None:
    """CallStatus can be imported from app.calls.states."""
    from app.calls.states import CallStatus, VALID_TRANSITIONS, validate_transition  # noqa: F401


# ---------------------------------------------------------------------------
# Task 1.1 RED: CallStatus enum exhaustive value test
# ---------------------------------------------------------------------------


EXPECTED_VALUES = {
    "queued",
    "dialing",
    "ringing",
    "connected",
    "voicemail",
    "completed",
    "no_answer",
    "failed",
    "recurrent_error",
    "stale_in_call",
}


def test_call_status_has_exactly_10_values() -> None:
    """CallStatus has exactly 10 values — no more, no less."""
    from app.calls.states import CallStatus

    actual = {member.value for member in CallStatus}
    assert actual == EXPECTED_VALUES, (
        f"Expected exactly {EXPECTED_VALUES}, got {actual}"
    )


def test_in_call_absent() -> None:
    """in_call must NOT be a value in CallStatus."""
    from app.calls.states import CallStatus

    values = {member.value for member in CallStatus}
    assert "in_call" not in values, "in_call must not exist in CallStatus"


def test_call_status_is_str_enum() -> None:
    """CallStatus members compare equal to plain strings (StrEnum contract)."""
    from app.calls.states import CallStatus

    assert CallStatus.dialing == "dialing"
    assert CallStatus.connected == "connected"
    assert CallStatus.completed == "completed"


# ---------------------------------------------------------------------------
# Task 1.1 RED: VALID_TRANSITIONS table — all expected edges present
# ---------------------------------------------------------------------------


EXPECTED_TRANSITIONS = [
    ("queued", "dialing"),
    ("dialing", "ringing"),
    ("ringing", "connected"),
    ("connected", "voicemail"),
    ("connected", "completed"),
    ("voicemail", "completed"),
    ("ringing", "no_answer"),
    ("dialing", "failed"),
    ("failed", "dialing"),          # retry path
    ("dialing", "recurrent_error"),
    ("ringing", "stale_in_call"),
    ("connected", "stale_in_call"),
]


@pytest.mark.parametrize("from_status,to_status", EXPECTED_TRANSITIONS)
def test_valid_transition_present_in_table(from_status: str, to_status: str) -> None:
    """Every expected valid transition is present in VALID_TRANSITIONS."""
    from app.calls.states import CallStatus, VALID_TRANSITIONS

    frm = CallStatus(from_status)
    to = CallStatus(to_status)
    assert to in VALID_TRANSITIONS.get(frm, set()), (
        f"Expected {from_status}→{to_status} to be in VALID_TRANSITIONS"
    )


# ---------------------------------------------------------------------------
# Task 1.1 RED: validate_transition() — valid transitions succeed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("from_status,to_status", EXPECTED_TRANSITIONS)
def test_validate_transition_valid_does_not_raise(from_status: str, to_status: str) -> None:
    """validate_transition() does not raise for any expected valid transition."""
    from app.calls.states import CallStatus, validate_transition

    validate_transition(CallStatus(from_status), CallStatus(to_status))


# ---------------------------------------------------------------------------
# Task 1.1 RED: validate_transition() — invalid transitions raise ValueError
# ---------------------------------------------------------------------------


INVALID_TRANSITIONS = [
    ("completed", "dialing"),    # terminal → active
    ("completed", "ringing"),
    ("no_answer", "completed"),  # terminal → terminal (different)
    ("ringing", "dialing"),      # backward
    ("connected", "dialing"),    # backward
    ("failed", "completed"),     # failed can only retry → dialing
    ("recurrent_error", "dialing"),  # recurrent_error is terminal
]


@pytest.mark.parametrize("from_status,to_status", INVALID_TRANSITIONS)
def test_validate_transition_invalid_raises_value_error(
    from_status: str, to_status: str
) -> None:
    """validate_transition() raises ValueError for invalid transitions."""
    from app.calls.states import CallStatus, validate_transition

    with pytest.raises(ValueError, match=r"[Ii]nvalid transition"):
        validate_transition(CallStatus(from_status), CallStatus(to_status))


# ---------------------------------------------------------------------------
# Task 2.1 RED: Concurrency guard — active set uses {dialing, ringing, connected}
# ---------------------------------------------------------------------------


def test_active_telephony_statuses_in_service_uses_enum() -> None:
    """_ACTIVE_TELEPHONY_STATUSES in outbound.service must include connected, not in_call."""
    from app.outbound.service import _ACTIVE_TELEPHONY_STATUSES

    assert "connected" in _ACTIVE_TELEPHONY_STATUSES, (
        "connected must be in _ACTIVE_TELEPHONY_STATUSES"
    )
    assert "in_call" not in _ACTIVE_TELEPHONY_STATUSES, (
        "in_call must NOT be in _ACTIVE_TELEPHONY_STATUSES"
    )
    assert "dialing" in _ACTIVE_TELEPHONY_STATUSES
    assert "ringing" in _ACTIVE_TELEPHONY_STATUSES


def test_active_telephony_statuses_exact_set() -> None:
    """_ACTIVE_TELEPHONY_STATUSES is exactly {dialing, ringing, connected}."""
    from app.outbound.service import _ACTIVE_TELEPHONY_STATUSES

    assert set(_ACTIVE_TELEPHONY_STATUSES) == {"dialing", "ringing", "connected"}


def test_stale_telephony_statuses_in_sweep_uses_connected() -> None:
    """_STALE_TELEPHONY_STATUSES in sweep must include connected, not in_call."""
    from app.outbound.sweep import _STALE_TELEPHONY_STATUSES

    assert "connected" in _STALE_TELEPHONY_STATUSES, (
        "connected must be in _STALE_TELEPHONY_STATUSES"
    )
    assert "in_call" not in _STALE_TELEPHONY_STATUSES, (
        "in_call must NOT be in _STALE_TELEPHONY_STATUSES"
    )
