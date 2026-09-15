"""QORA ElevenLabs — Pydantic models for API request/response contracts.

SoftTimeoutConfig: represents the soft_timeout_config block sent to ElevenLabs ConvAI API.
SyncResult: represents the outcome of a sync attempt.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Literal

from pydantic import BaseModel, model_validator


class SoftTimeoutConfig(BaseModel):
    """ElevenLabs ConvAI soft_timeout_config block.

    Verified field names against real ElevenLabs API (2026-05-24):
    - timeout_seconds (NOT timeout_secs)
    - message
    - use_llm_generated_message (NOT use_llm)
    """

    timeout_seconds: float | None = None
    message: str | None = None
    use_llm_generated_message: bool | None = None

    def to_patch_payload(self) -> dict:
        """Build the PATCH body for the ElevenLabs ConvAI agent endpoint.

        Returns only the conversation_config.turn.soft_timeout_config block.
        Only includes fields that are not None — ElevenLabs preserves unset fields.
        """
        stc: dict = {}
        if self.timeout_seconds is not None:
            stc["timeout_seconds"] = self.timeout_seconds
        if self.message is not None:
            stc["message"] = self.message
        if self.use_llm_generated_message is not None:
            stc["use_llm_generated_message"] = self.use_llm_generated_message

        if not stc:
            return {}

        return {"conversation_config": {"turn": {"soft_timeout_config": stc}}}


class SyncResult(BaseModel):
    """Result of an ElevenLabs sync attempt.

    outcome:
        "synced"  — PATCH succeeded (2xx response)
        "skipped" — No HTTP call made (missing agent_id or all fields None)
        "error"   — PATCH failed after retry (5xx) or timed out
    error_detail: Human-readable error string, None when outcome != "error"
    """

    outcome: Literal["synced", "skipped", "error"]
    error_detail: str | None = None


# ---------------------------------------------------------------------------
# C2 — Outbound call API models
# ---------------------------------------------------------------------------


class OutboundCallRequest(BaseModel):
    """Request body for the ElevenLabs SIP trunk outbound-call API.

    POST https://api.elevenlabs.io/v1/convai/sip-trunk/outbound-call

    Fields verified against ElevenLabs ConvAI outbound-call API (2026-07-04):
      - agent_id: ElevenLabs agent identifier
      - agent_phone_number_id: ElevenLabs phone number resource ID (from SIP trunk setup)
      - to: Destination number in E.164 format. Serialized to the wire as "to_number"
            (the API's required field name) in ElevenLabsService.initiate_outbound_call().
      - conversation_initiation_client_data: Optional dict with two supported keys:
          "dynamic_variables": flat dict of template variables for {{var}} substitution
              in the agent prompt. Without this wrapper ElevenLabs ignores the values.
          "custom_llm_extra_body": flat dict forwarded verbatim to the Custom LLM
              endpoint as the `elevenlabs_extra_body` field. Used to carry client_id
              and lead_id to the Custom LLM handler for outbound call session routing.
    """

    agent_id: str
    agent_phone_number_id: str
    to: str  # E.164; sent as "to_number" on the wire — validated before construction
    conversation_initiation_client_data: dict | None = None


class OutboundCallResult(BaseModel):
    """Result of an ElevenLabs outbound-call API attempt.

    outcome:
        "accepted" — API returned 2xx; provider_call_id is set
        "error"    — API returned an error or network failure occurred

    error_category:
        "transient"  — 5xx, 429, connect errors (request never sent → retry eligible)
        "permanent"  — 4xx (non-429) errors (do not retry)
        "no_answer"  — provider reports no answer / ring timeout (do not retry;
                        distinct from system failure — leads status = 'no_answer')
        "unknown"    — read/write timeout AFTER the request was sent. The provider
                        may have already created/placed the SIP call, so the side
                        effect is ambiguous. MUST NOT be retried — retrying dials a
                        second real (billed) call. Session goes to 'failed' pending
                        reconciliation, never re-dialed automatically.
        None          — when outcome == "accepted"

    provider_call_id: ElevenLabs call identifier (set when accepted).
    provider_metadata: Safe/allowlisted API response fields (cost, billed_duration_seconds, etc.).
        Only fields from the approved allowlist are persisted — PII and routing data are dropped.
    error_detail: Human-readable error string (set when outcome == "error").
    """

    outcome: Literal["accepted", "error"]
    provider_call_id: str | None = None
    provider_metadata: dict | None = None
    error_detail: str | None = None
    error_category: Literal["transient", "permanent", "no_answer", "unknown"] | None = None


# ---------------------------------------------------------------------------
# C3 — Call SIP Observability models
# ---------------------------------------------------------------------------


class ConversationSummary(BaseModel):
    """Single conversation from ElevenLabs list endpoint.

    Only safe, structured fields are captured here. Phone numbers, SIP URIs,
    caller metadata, and any free-form provider text are NOT included.
    """

    conversation_id: str
    agent_id: str | None = None
    status: str | None = None  # "done", "processing", etc.
    call_successful: str | None = None
    start_time_unix_secs: int | None = None
    # Structured metadata only — no raw SIP trace or phone-number fields
    metadata: dict | None = None

    model_config = {"extra": "ignore"}


class ConversationListResponse(BaseModel):
    """Response from GET /convai/conversations."""

    conversations: list[ConversationSummary] = []

    model_config = {"extra": "ignore"}


_MAX_RAW_SIP_CHARS = 4096
_MAX_CALL_ID_CHARS = 256
_MAX_REASON_CHARS = 128
_MAX_TIMESTAMP_CHARS = 64
_SIP_STATUS_LINE = re.compile(r"^SIP/2\.0\s+(\d{3})(?:\s+([^\r\n]{0,128}))?$")
_SIP_REQUEST_LINE = re.compile(r"^([A-Z]{1,16})\s+[^\r\n]+\s+SIP/2\.0$")
_SIP_CSEQ_LINE = re.compile(r"(?mi)^CSeq\s*:\s*(\d{1,10})\s+([A-Z]{1,16})\s*$")
_SIP_CSEQ_HEADER = re.compile(r"(?mi)^CSeq\s*:")
_SAFE_REASON = re.compile(r"^[A-Za-z0-9 .,'()/_-]{0,128}$")
_DIRECTION_ALIASES = {
    "in": "inbound",
    "out": "outbound",
    "inbound": "inbound",
    "outbound": "outbound",
}


def _timestamp_from_unix_micro(value: object) -> str | None:
    """Return a UTC ISO timestamp without exposing malformed provider values."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    try:
        return datetime.fromtimestamp(value / 1_000_000, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


class SipMessage(BaseModel):
    """Sanitized SIP message — extracted structured fields only.

    Upstream ``raw_message`` and ``error_message`` are reduced before model
    construction; neither can appear in model dumps, reprs, or validation errors.
    """

    call_id: str | None = None
    method: str | None = None
    status_code: int | None = None
    reason_phrase: str | None = None
    direction: str | None = None
    timestamp: str | None = None
    cseq: int | None = None

    @model_validator(mode="before")
    @classmethod
    def sanitize_provider_message(cls, value: Any) -> dict[str, object]:
        """Allowlist legacy fields or derive safe fields from bounded raw SIP text."""
        if not isinstance(value, dict):
            return {}

        sanitized: dict[str, object] = {}
        call_id = value.get("call_id")
        if isinstance(call_id, str) and len(call_id) <= _MAX_CALL_ID_CHARS:
            sanitized["call_id"] = call_id
        direction = value.get("direction")
        if isinstance(direction, str) and direction in _DIRECTION_ALIASES:
            sanitized["direction"] = _DIRECTION_ALIASES[direction]

        raw_message = value.get("raw_message")
        if isinstance(raw_message, str):
            if len(raw_message) > _MAX_RAW_SIP_CHARS:
                return sanitized

            header_section = re.split(r"\r?\n\r?\n", raw_message, maxsplit=1)[0]
            first_line = header_section.splitlines()[0] if header_section else ""
            status_match = _SIP_STATUS_LINE.fullmatch(first_line)
            request_match = _SIP_REQUEST_LINE.fullmatch(first_line)
            if not status_match and not request_match:
                return sanitized

            cseq_matches = list(_SIP_CSEQ_LINE.finditer(header_section))
            if (
                len(cseq_matches) != 1
                or len(_SIP_CSEQ_HEADER.findall(header_section)) != 1
            ):
                return sanitized
            cseq_match = cseq_matches[0]
            cseq_method = cseq_match.group(2)
            if request_match and request_match.group(1) != cseq_method:
                return sanitized

            if status_match:
                status_code = int(status_match.group(1))
                if not 100 <= status_code <= 699:
                    return sanitized
                sanitized["status_code"] = status_code
                reason = (status_match.group(2) or "").strip()
                if reason and _SAFE_REASON.fullmatch(reason):
                    sanitized["reason_phrase"] = reason
            sanitized["cseq"] = int(cseq_match.group(1))
            sanitized["method"] = cseq_method
            timestamp = _timestamp_from_unix_micro(value.get("created_at_unix_micro"))
            if timestamp is not None:
                sanitized["timestamp"] = timestamp
            return sanitized

        # Legacy normalized fixtures are already safe and remain supported.
        for field in ("method", "reason_phrase", "timestamp"):
            field_value = value.get(field)
            limit = (
                _MAX_REASON_CHARS if field == "reason_phrase" else _MAX_TIMESTAMP_CHARS
            )
            if isinstance(field_value, str) and len(field_value) <= limit:
                sanitized[field] = field_value
        status_code = value.get("status_code")
        if (
            isinstance(status_code, int)
            and not isinstance(status_code, bool)
            and 100 <= status_code <= 699
        ):
            sanitized["status_code"] = status_code
        cseq = value.get("cseq")
        if isinstance(cseq, int) and not isinstance(cseq, bool) and cseq >= 0:
            sanitized["cseq"] = cseq
        return sanitized

    model_config = {"extra": "ignore"}


class SipMessagesResponse(BaseModel):
    """Response from GET /sip-messages endpoints, including cursor completeness."""

    sip_messages: list[SipMessage] = []
    has_more: bool | None = None
    next_cursor: str | None = None

    @model_validator(mode="before")
    @classmethod
    def sanitize_provider_response(cls, value: Any) -> dict[str, object]:
        """Drop malformed items before Pydantic can include provider bytes in errors."""
        if not isinstance(value, dict):
            return {"sip_messages": []}
        messages = value.get("sip_messages")
        sanitized: dict[str, object] = {
            "sip_messages": [item for item in messages if isinstance(item, dict)]
            if isinstance(messages, list)
            else []
        }
        if isinstance(value.get("has_more"), bool):
            sanitized["has_more"] = value["has_more"]
        if isinstance(value.get("next_cursor"), str):
            sanitized["next_cursor"] = value["next_cursor"]
        return sanitized

    model_config = {"extra": "ignore"}
