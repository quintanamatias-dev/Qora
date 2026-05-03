"""QORA — Post-call analysis package.

Self-contained: only imports pydantic and enum. NO app dependencies (no
FastAPI, no SQLAlchemy, no structlog) outside of this package's own modules
so the package can be copy-pasted into other runtimes.

Each universal dimension under ``app.analysis.universal`` owns its own
prompt, schema, and an ``analyze(transcript, client)`` coroutine. The
summarizer fans 10 calls out via ``asyncio.gather`` for the independent
dimensions PLUS runs the 2-phase interest pipeline sequentially.

qora-interest-pipeline: DetectedInterests (old flat-list model) replaced by
InterestsAxis (catalog-validated model from interest/ package).

qora-abandonment: AbandonmentReasonAxis removed. Abandonment signal now lives
in CallOutcome as was_abrupt + abandonment_trigger. DIMENSION_MODULES: 11 → 10.
"""

from __future__ import annotations

from app.analysis.enums import Urgency
from app.analysis.schema import PostCallAnalysis
from app.analysis.universal import (
    AbandonmentTrigger,
    CallOutcome,
    CommitmentsAxis,
    DIMENSION_MODULES,
    IdentifiedProblem,
    InterestsAxis,
    PainPoint,
    ProblemAxis,
    ProfileFactsAxis,
    ServiceIssue,
    ServiceIssuesAxis,
    UNIVERSAL_DIMENSIONS,
)

__all__ = [
    "Urgency",
    "CallOutcome",
    "AbandonmentTrigger",
    "InterestsAxis",
    "IdentifiedProblem",
    "PainPoint",
    "ProblemAxis",
    "ServiceIssue",
    "ServiceIssuesAxis",
    "ProfileFactsAxis",
    "CommitmentsAxis",
    "PostCallAnalysis",
    "UNIVERSAL_DIMENSIONS",
    "DIMENSION_MODULES",
]
