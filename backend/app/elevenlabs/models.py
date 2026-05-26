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
