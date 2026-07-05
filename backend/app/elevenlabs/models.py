"""QORA ElevenLabs — Pydantic models for API request/response contracts.

SoftTimeoutConfig: represents the soft_timeout_config block sent to ElevenLabs ConvAI API.
SyncResult: represents the outcome of a sync attempt.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


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
      - conversation_initiation_client_data: Optional dynamic variables for the agent prompt
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


class SipMessage(BaseModel):
    """Sanitized SIP message — extracted structured fields only.

    Design: SIP field extraction — allowlist only, never raw bodies.

    Allowed fields (spec: Structured-Field-Only SIP Extraction):
      call_id       — SIP Call-ID header value (e.g. "otb_...")
      method        — INVITE, BYE, CANCEL, etc.
      status_code   — Integer response code (200, 404, 487, etc.)
      reason_phrase — Human-readable reason ("OK", "Not Found", etc.)
      direction     — "inbound" / "outbound"
      timestamp     — ISO 8601 message timestamp

    Explicitly EXCLUDED (spec: secrets excluded):
      raw_body            — SIP message body (may contain Proxy-Authorization, PII)
      proxy_authorization — SIP digest credential header
      authorization       — SIP authorization header
      from_uri / to_uri   — SIP URIs containing phone numbers
    """

    call_id: str | None = None
    method: str | None = None
    status_code: int | None = None
    reason_phrase: str | None = None
    direction: str | None = None
    timestamp: str | None = None

    # Reject any extra fields to prevent raw-body leakage via unknown keys
    model_config = {"extra": "ignore"}


class SipMessagesResponse(BaseModel):
    """Response from GET /conversations/{id}/sip_messages."""

    sip_messages: list[SipMessage] = []

    model_config = {"extra": "ignore"}
