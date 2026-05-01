"""QORA — Post-call analysis package.

Self-contained: only imports pydantic and enum. NO app dependencies (no
FastAPI, no SQLAlchemy, no structlog) outside of this package's own modules
so the package can be copy-pasted into other runtimes.

Each universal dimension under ``app.analysis.universal`` owns its own
prompt, schema, and an ``analyze(transcript, client)`` coroutine. The
summarizer fans 13 calls out via ``asyncio.gather`` and assembles the
results into ``PostCallAnalysis``.
"""

from __future__ import annotations

from app.analysis.enums import EngagementQuality, OutcomeClassification, Urgency
from app.analysis.schema import PostCallAnalysis
from app.analysis.universal import (
    AbandonmentReasonAxis,
    CallOutcome,
    CommitmentsAxis,
    DetectedInterests,
    DIMENSION_MODULES,
    IdentifiedProblem,
    ProfileFactsAxis,
    ServiceIssue,
    ServiceIssuesAxis,
    UNIVERSAL_DIMENSIONS,
)

__all__ = [
    "OutcomeClassification",
    "EngagementQuality",
    "Urgency",
    "CallOutcome",
    "DetectedInterests",
    "IdentifiedProblem",
    "ServiceIssue",
    "ServiceIssuesAxis",
    "ProfileFactsAxis",
    "CommitmentsAxis",
    "AbandonmentReasonAxis",
    "PostCallAnalysis",
    "UNIVERSAL_DIMENSIONS",
    "DIMENSION_MODULES",
]
