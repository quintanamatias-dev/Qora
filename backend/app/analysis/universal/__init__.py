"""Universal analysis dimensions — applied to every client by default.

Each module in this package owns a Pydantic schema, a focused system prompt,
and an ``analyze(transcript, client)`` coroutine that runs ONE OpenAI call
and returns the unwrapped value that drops directly into PostCallAnalysis.

qora-interest-pipeline: The summarizer now runs independent dimensions in
parallel (``DIMENSION_MODULES``) PLUS a sequential 2-phase interest pipeline
via ``run_interest_pipeline``. The old ``interests`` and ``interest_level``
modules are no longer in ``DIMENSION_MODULES`` — they are orchestrated by
the pipeline.

qora-abandonment: ``abandonment`` dimension removed (11 → 10 DIMENSION_MODULES).
Abandonment signal absorbed into ``CallOutcome`` as ``was_abrupt`` + ``abandonment_trigger``.

qora-profile-facts: ``profile_facts`` schema rewritten to operation-based model
(ProfileFactUpdate / ProfileFactsAxis with max 5 updates). ``run_profile_facts_pipeline``
is exported for use by the summarizer (Phase 2 removes profile_facts from DIMENSION_MODULES).

qora-misc-notes: ``misc_notes`` extracted from DIMENSION_MODULES (9 → 8).
Now a standalone stateful pipeline via ``run_misc_notes_pipeline``.
Schema changed from ``str`` to ``MiscNotesAxis(notes: list[MiscNote])``.

qora-data-corrections: ``data_corrections`` extracted from DIMENSION_MODULES (8 → 7).
Now a standalone stateful pipeline via ``run_data_corrections_pipeline``.
Requires current lead snapshot as input (like profile_facts, stateful).

qora-next-action: ``next_action`` removed from DIMENSION_MODULES (7 → 6).
Promoted to post-analysis pipeline via ``run_next_action_pipeline``.
"""

from __future__ import annotations

from types import ModuleType

from app.analysis.universal import (
    commitments,
    data_corrections,  # noqa: F401 — kept for direct access; not in DIMENSION_MODULES
    misc_notes,  # noqa: F401 — qora-misc-notes: no longer in DIMENSION_MODULES but kept for direct access in tests
    # qora-next-action: next_action removed from DIMENSION_MODULES; module kept for pipeline use
    next_action,  # noqa: F401 — kept for run_next_action_pipeline direct access
    objections,
    outcome,
    problem,
    # qora-profile-facts: profile_facts module no longer in DIMENSION_MODULES.
    # Kept imported only if used directly; its symbols come from the explicit import below.
    service_issues,
    summary,
)

# qora-misc-notes: MiscNote and run_misc_notes_pipeline exported for summarizer use
from app.analysis.universal.commitments import CommitmentsAxis
from app.analysis.universal.data_corrections import (
    DataCorrection,
    DataCorrectionsAxis,
    run_data_corrections_pipeline,
)

# qora-interest-pipeline: InterestItem, InterestsAxis, InterestLevelResult,
# and run_interest_pipeline are imported from the new interest/ package.
from app.analysis.universal.interest import (
    InterestItem,
    InterestLevelResult,
    InterestsAxis,
    run_interest_pipeline,
)
from app.analysis.universal.misc_notes import (
    MiscNote,
    MiscNotesAxis,
    run_misc_notes_pipeline,
)
from app.analysis.universal.next_action import (
    NextActionResult,
    run_next_action_pipeline,
)
from app.analysis.universal.objections import Objection, ObjectionsAxis
from app.analysis.universal.outcome import AbandonmentTrigger, CallOutcome
from app.analysis.universal.problem import IdentifiedProblem, PainPoint, ProblemAxis
from app.analysis.universal.profile_facts import (
    ProfileFactCategory,
    ProfileFactUpdate,
    ProfileFactsAxis,
    run_profile_facts_pipeline,
)
from app.analysis.universal.service_issues import ServiceIssue, ServiceIssuesAxis
from app.analysis.universal.summary import SummaryAxis

# Ordered list of dimension modules — one entry per per-dimension analyzer.
# The summarizer fans out one OpenAI call per module via ``mod.analyze`` and
# merges the unwrapped results into PostCallAnalysis using ``DIMENSION["target_field"]``.
#
# qora-interest-pipeline: DIMENSION_MODULES had 11 entries (down from 13).
# qora-abandonment: DIMENSION_MODULES now has 10 entries (abandonment removed).
# qora-profile-facts: profile_facts removed from DIMENSION_MODULES (10 → 9).
# qora-misc-notes: misc_notes removed from DIMENSION_MODULES (9 → 8).
# qora-data-corrections: data_corrections removed from DIMENSION_MODULES (8 → 7).
#   Replaced by standalone run_data_corrections_pipeline() for stateful execution
#   (requires current lead snapshot — dimensions are stateless).
# qora-next-action: next_action removed from DIMENSION_MODULES (7 → 6).
#   Promoted to post-analysis pipeline via run_next_action_pipeline().
DIMENSION_MODULES: list[ModuleType] = [
    summary,
    objections,
    outcome,
    problem,
    service_issues,
    commitments,
]

UNIVERSAL_DIMENSIONS: list[dict] = [mod.DIMENSION for mod in DIMENSION_MODULES]

__all__ = [
    "SummaryAxis",
    "Objection",
    "ObjectionsAxis",
    # qora-next-action: NextActionAxis removed; new engine symbols exported
    "NextActionResult",
    "run_next_action_pipeline",
    "MiscNote",
    "MiscNotesAxis",
    "run_misc_notes_pipeline",
    "DataCorrection",
    "DataCorrectionsAxis",
    "run_data_corrections_pipeline",
    "CallOutcome",
    "AbandonmentTrigger",
    "IdentifiedProblem",
    "PainPoint",
    "ProblemAxis",
    "ServiceIssue",
    "ServiceIssuesAxis",
    "ProfileFactCategory",
    "ProfileFactUpdate",
    "ProfileFactsAxis",
    "run_profile_facts_pipeline",
    "CommitmentsAxis",
    # qora-interest-pipeline: new exports from interest/ package
    "InterestItem",
    "InterestsAxis",
    "InterestLevelResult",
    "run_interest_pipeline",
    # Module collections
    "UNIVERSAL_DIMENSIONS",
    "DIMENSION_MODULES",
]
