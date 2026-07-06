"""QORA Calls — Formal CallStatus state machine.

Defines the canonical telephony status enum and explicit transition allowlist
used throughout the outbound calling pipeline.

Design decisions (design.md):
  - StrEnum: members compare equal to plain strings, safe for DB column reads.
  - Dedicated module (not in models.py): avoids circular imports when
    service/probe/sweep/linkage all import this. Single source of truth.
  - VALID_TRANSITIONS: explicit dict[CallStatus, set[CallStatus]] — readable,
    testable, not hidden inside enum methods.
  - validate_transition(): pure function, raises ValueError on invalid path.
    Never mutates state — callers write to the DB column directly.

Spec: call-state-machine — Requirements:
  - CallStatus Enum: 10 values; in_call MUST NOT exist.
  - Explicit Transition Table: invalid transitions raise ValueError.
  - Concurrency Guard Updated: {dialing, ringing, connected} — not in_call.

State machine diagram:
  queued → dialing → ringing → connected → completed
                            ↘ voicemail → completed
                   ↘ no_answer
          ↘ failed → dialing (retry)
          ↘ recurrent_error
                              connected → stale_in_call
                    ringing   → stale_in_call
"""

from __future__ import annotations

from enum import StrEnum


class CallStatus(StrEnum):
    """Canonical telephony lifecycle states for an outbound CallSession.

    Values are stored as strings in the call_sessions.telephony_status column.
    StrEnum membership means CallStatus.dialing == "dialing" is True.
    """

    queued = "queued"               # Pre-dial — scheduler queued, not yet attempted
    dialing = "dialing"             # API call sent to ElevenLabs, awaiting acceptance
    ringing = "ringing"             # ElevenLabs accepted; SIP INVITE in-flight
    connected = "connected"         # SIP 200 OK received — call is live (replaces in_call)
    voicemail = "voicemail"         # Heuristic: short duration + no user turns
    completed = "completed"         # Session-end webhook confirmed real conversation
    no_answer = "no_answer"         # SIP routing failure or ring timeout
    failed = "failed"               # Provider/system error
    recurrent_error = "recurrent_error"  # Two consecutive transient failures
    stale_in_call = "stale_in_call"     # Sweep safety net: stuck without session-end evidence


# ---------------------------------------------------------------------------
# Explicit transition allowlist
#
# Design: dict table is explicit, testable, and readable. Methods on the enum
# would hide valid transitions inside the class — harder to audit.
#
# Reading: VALID_TRANSITIONS[from_status] → set of permitted to_status values.
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[CallStatus, set[CallStatus]] = {
    CallStatus.queued: {CallStatus.dialing},
    CallStatus.dialing: {
        CallStatus.ringing,
        CallStatus.failed,
        CallStatus.recurrent_error,
    },
    CallStatus.ringing: {
        CallStatus.connected,
        CallStatus.no_answer,
        CallStatus.stale_in_call,
    },
    CallStatus.connected: {
        CallStatus.voicemail,
        CallStatus.completed,
        CallStatus.stale_in_call,
    },
    CallStatus.voicemail: {CallStatus.completed},
    # failed → dialing enables one retry attempt
    CallStatus.failed: {CallStatus.dialing},
    # Terminal states — no outgoing transitions
    CallStatus.completed: set(),
    CallStatus.no_answer: set(),
    CallStatus.recurrent_error: set(),
    CallStatus.stale_in_call: set(),
}


def validate_transition(from_status: CallStatus, to_status: CallStatus) -> None:
    """Assert that the state transition from_status → to_status is permitted.

    Raises:
        ValueError: If the transition is not in VALID_TRANSITIONS.

    Args:
        from_status: Current CallStatus value.
        to_status:   Target CallStatus value.
    """
    allowed = VALID_TRANSITIONS.get(from_status, set())
    if to_status not in allowed:
        raise ValueError(
            f"Invalid transition: {from_status!r} → {to_status!r}. "
            f"Allowed from {from_status!r}: {sorted(s.value for s in allowed) or 'none (terminal state)'}"
        )
