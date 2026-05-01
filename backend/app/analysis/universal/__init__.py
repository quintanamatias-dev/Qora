"""Universal analysis dimensions — applied to every client by default.

Each module in this package owns a Pydantic schema, a focused system prompt,
and an ``analyze(transcript, client)`` coroutine that runs ONE OpenAI call
and returns the unwrapped value that drops directly into PostCallAnalysis.

The summarizer iterates ``DIMENSION_MODULES`` (one entry per module) and runs
all 13 ``analyze`` coroutines in parallel via ``asyncio.gather``.
"""

from __future__ import annotations

from types import ModuleType

from app.analysis.universal import (
    abandonment,
    commitments,
    data_corrections,
    interest_level,
    interests,
    misc_notes,
    next_action,
    objections,
    outcome,
    problem,
    profile_facts,
    service_issues,
    summary,
)
from app.analysis.universal.abandonment import AbandonmentReasonAxis
from app.analysis.universal.commitments import CommitmentsAxis
from app.analysis.universal.data_corrections import DataCorrectionsAxis
from app.analysis.universal.interest_level import InterestLevelAxis
from app.analysis.universal.interests import DetectedInterests
from app.analysis.universal.misc_notes import MiscNotesAxis
from app.analysis.universal.next_action import NextActionAxis
from app.analysis.universal.objections import ObjectionsAxis
from app.analysis.universal.outcome import CallOutcome
from app.analysis.universal.problem import IdentifiedProblem
from app.analysis.universal.profile_facts import ProfileFactsAxis
from app.analysis.universal.service_issues import ServiceIssuesAxis
from app.analysis.universal.summary import SummaryAxis

# Ordered list of dimension modules — one entry per per-dimension analyzer.
# The summarizer fans out one OpenAI call per module via ``mod.analyze`` and
# merges the unwrapped results into PostCallAnalysis using ``DIMENSION["target_field"]``.
DIMENSION_MODULES: list[ModuleType] = [
    summary,
    objections,
    interest_level,
    next_action,
    misc_notes,
    data_corrections,
    outcome,
    interests,
    problem,
    service_issues,
    profile_facts,
    commitments,
    abandonment,
]

UNIVERSAL_DIMENSIONS: list[dict] = [mod.DIMENSION for mod in DIMENSION_MODULES]

__all__ = [
    "SummaryAxis",
    "ObjectionsAxis",
    "InterestLevelAxis",
    "NextActionAxis",
    "MiscNotesAxis",
    "DataCorrectionsAxis",
    "CallOutcome",
    "DetectedInterests",
    "IdentifiedProblem",
    "ServiceIssuesAxis",
    "ProfileFactsAxis",
    "CommitmentsAxis",
    "AbandonmentReasonAxis",
    "UNIVERSAL_DIMENSIONS",
    "DIMENSION_MODULES",
]
