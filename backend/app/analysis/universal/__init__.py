"""Universal analysis dimensions — applied to every client by default.

Each module in this package exposes a Pydantic model plus a DIMENSION dict
with metadata for per-branch n8n GPT calls (focused prompt, default model,
schema reference). UNIVERSAL_DIMENSIONS aggregates the metadata so an
orchestrator can iterate dimensions without importing each module by name.
"""

from __future__ import annotations

from app.analysis.universal.abandonment import AbandonmentReasonAxis
from app.analysis.universal.abandonment import DIMENSION as ABANDONMENT_DIMENSION
from app.analysis.universal.commitments import CommitmentSignalsAxis
from app.analysis.universal.commitments import DIMENSION as COMMITMENTS_DIMENSION
from app.analysis.universal.data_corrections import DataCorrectionsAxis
from app.analysis.universal.data_corrections import DIMENSION as DATA_CORRECTIONS_DIMENSION
from app.analysis.universal.interest_level import InterestLevelAxis
from app.analysis.universal.interest_level import DIMENSION as INTEREST_LEVEL_DIMENSION
from app.analysis.universal.interests import DetectedInterests
from app.analysis.universal.interests import DIMENSION as INTERESTS_DIMENSION
from app.analysis.universal.misc_notes import MiscNotesAxis
from app.analysis.universal.misc_notes import DIMENSION as MISC_NOTES_DIMENSION
from app.analysis.universal.next_action import NextActionAxis
from app.analysis.universal.next_action import DIMENSION as NEXT_ACTION_DIMENSION
from app.analysis.universal.objections import ObjectionsAxis
from app.analysis.universal.objections import DIMENSION as OBJECTIONS_DIMENSION
from app.analysis.universal.outcome import CallOutcome
from app.analysis.universal.outcome import DIMENSION as OUTCOME_DIMENSION
from app.analysis.universal.problem import IdentifiedProblem
from app.analysis.universal.problem import DIMENSION as PROBLEM_DIMENSION
from app.analysis.universal.profile_facts import ProfileFactsAxis
from app.analysis.universal.profile_facts import DIMENSION as PROFILE_FACTS_DIMENSION
from app.analysis.universal.service_issues import ServiceIssuesAxis
from app.analysis.universal.service_issues import DIMENSION as SERVICE_ISSUES_DIMENSION
from app.analysis.universal.summary import SummaryAxis
from app.analysis.universal.summary import DIMENSION as SUMMARY_DIMENSION

UNIVERSAL_DIMENSIONS: list[dict] = [
    SUMMARY_DIMENSION,
    OBJECTIONS_DIMENSION,
    INTEREST_LEVEL_DIMENSION,
    NEXT_ACTION_DIMENSION,
    MISC_NOTES_DIMENSION,
    DATA_CORRECTIONS_DIMENSION,
    OUTCOME_DIMENSION,
    INTERESTS_DIMENSION,
    PROBLEM_DIMENSION,
    SERVICE_ISSUES_DIMENSION,
    PROFILE_FACTS_DIMENSION,
    COMMITMENTS_DIMENSION,
    ABANDONMENT_DIMENSION,
]

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
    "CommitmentSignalsAxis",
    "AbandonmentReasonAxis",
    "UNIVERSAL_DIMENSIONS",
]
