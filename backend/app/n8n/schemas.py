"""QORA n8n — Pydantic v2 schemas for n8n orchestration payloads.

Three schema families:
- N8nTriggerPayload: sent from backend → n8n webhook on call end
- N8nCallbackPayload: sent from n8n → backend analysis callback endpoint
- VerificationResult: produced internally by comparison logic
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Outbound: Backend → n8n
# ---------------------------------------------------------------------------


class N8nTriggerPayload(BaseModel):
    """Payload fired from _schedule_summarize to the n8n webhook trigger.

    Fields:
        session_id: UUID of the call session to analyze.
        client_id: UUID of the client (used to fetch extraction config).
        timestamp: ISO 8601 UTC timestamp of when the trigger was fired.
    """

    session_id: str
    client_id: str
    timestamp: str  # ISO 8601 UTC — e.g. "2026-04-28T10:00:00Z"


# ---------------------------------------------------------------------------
# Inbound: n8n → Backend callback
# ---------------------------------------------------------------------------


class N8nCallbackPayload(BaseModel):
    """Payload POSTed by n8n to /api/v1/internal/analysis-result.

    Spec contract: {session_id, summary, facts}
    The 'status' field is NOT required by the spec — only session_id is mandatory.

    Fields:
        session_id: UUID of the analyzed call session (required).
        summary: Generated summary text from GPT analysis.
        facts: Extracted facts dict matching PostCallAnalysis shape.
        n8n_execution_id: Optional n8n execution UUID for correlation.
    """

    session_id: str
    summary: str | None = None
    facts: dict[str, Any] | None = None
    n8n_execution_id: str | None = None


# ---------------------------------------------------------------------------
# Internal: comparison result from verification logic
# ---------------------------------------------------------------------------


class VerificationResult(BaseModel):
    """Result of comparing n8n analysis output against local pipeline output.

    Fields:
        session_id: UUID of the analyzed call session.
        agreement: True if outputs match, False if they diverge, None if local
            pipeline has not yet completed (pending state).
        matching_fields: List of field names where both pipelines agreed.
        divergent_fields: List of field names where outputs differ.
        details: Per-field comparison detail: {field: {local, n8n, match}}.
    """

    session_id: str
    agreement: bool | None
    matching_fields: list[str]
    divergent_fields: list[str]
    details: dict[str, Any]
