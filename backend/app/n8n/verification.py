"""QORA n8n — Dual-write verification and comparison logging.

Compares n8n analysis output against local pipeline output and logs
structured comparison entries for agreement rate tracking.

Design decision: verification uses structlog JSON lines (no new DB table).
Log entries are queryable via the observability stack.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.n8n.schemas import VerificationResult

logger = structlog.get_logger(__name__)

# Fields to compare between local and n8n pipeline outputs
_COMPARISON_FIELDS = [
    "interest_level",
    "next_action_suggested",
    "current_insurance",
]


def _hash_value(value: Any) -> str:
    """Produce a short, stable hash of any JSON-serializable value.

    Args:
        value: Any JSON-serializable value.

    Returns:
        8-character hex digest (truncated SHA-256).
    """
    normalized = json.dumps(value, sort_keys=True, default=str)
    return hashlib.sha256(normalized.encode()).hexdigest()[:8]


def compare_results(
    session_id: str,
    local_facts: dict[str, Any] | None,
    n8n_facts: dict[str, Any] | None,
) -> VerificationResult:
    """Compare local pipeline facts against n8n pipeline facts field-by-field.

    When local_facts is None (local pipeline not yet completed), returns
    agreement=False with a pending indicator in details.

    Args:
        session_id: UUID of the call session being compared.
        local_facts: Facts extracted by the local summarizer pipeline.
        n8n_facts: Facts extracted by the n8n pipeline.

    Returns:
        VerificationResult with agreement status and field-level details.
    """
    if local_facts is None:
        # Local pipeline not yet complete — log as pending (agreed=None per spec)
        return VerificationResult(
            session_id=session_id,
            agreement=None,
            matching_fields=[],
            divergent_fields=["_all"],
            details={"_pending": "local pipeline not yet complete"},
        )

    matching: list[str] = []
    divergent: list[str] = []
    details: dict[str, Any] = {}

    for field in _COMPARISON_FIELDS:
        local_val = local_facts.get(field)
        n8n_val = n8n_facts.get(field) if n8n_facts else None
        match = local_val == n8n_val
        details[field] = {
            "local": local_val,
            "n8n": n8n_val,
            "match": match,
        }
        if match:
            matching.append(field)
        else:
            divergent.append(field)

    return VerificationResult(
        session_id=session_id,
        agreement=len(divergent) == 0,
        matching_fields=matching,
        divergent_fields=divergent,
        details=details,
    )


async def log_verification_comparison(
    session_id: str,
    n8n_summary: str,
    n8n_facts: dict[str, Any] | None,
    db: AsyncSession,
) -> None:
    """Fetch local analysis result and log a structured comparison entry.

    Logs a JSON line with session_id, agreed, n8n_summary_hash,
    local_summary_hash, and timestamp.

    Args:
        session_id: UUID of the analyzed call session.
        n8n_summary: Summary returned by n8n pipeline.
        n8n_facts: Facts returned by n8n pipeline.
        db: Active DB session (used to read local CallAnalysis).
    """
    from sqlalchemy import select
    from app.calls.models import CallAnalysis

    # Load local analysis (may not yet exist if local pipeline is still running)
    ca_result = await db.execute(
        select(CallAnalysis).where(CallAnalysis.session_id == session_id)
    )
    ca = ca_result.scalar_one_or_none()

    local_facts: dict[str, Any] | None = None
    local_summary: str | None = None
    if ca is not None and ca.analysis_status == "ok":
        local_summary = ca.summary
        local_facts = {
            "interest_level": ca.interest_level,
            "next_action_suggested": ca.next_action_suggested,
            "current_insurance": ca.current_insurance,
            "classification": ca.classification,
        }

    result = compare_results(session_id, local_facts, n8n_facts)

    logger.info(
        "n8n_verification_comparison",
        session_id=session_id,
        agreed=result.agreement,  # None when local pipeline pending, bool otherwise
        n8n_summary_hash=_hash_value(n8n_summary),
        local_summary_hash=_hash_value(local_summary),
        matching_fields=result.matching_fields,
        divergent_fields=result.divergent_fields,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
