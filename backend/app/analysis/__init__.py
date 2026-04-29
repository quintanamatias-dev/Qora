"""QORA — Post-call analysis package.

Self-contained: only imports pydantic, enum, re, json, collections, functools.
NO app dependencies (no FastAPI, no SQLAlchemy, no structlog) outside of this
package's own modules — preserves the N8N migration boundary so the webhook
handler can copy this directory wholesale.
"""

from __future__ import annotations

from app.analysis.builder import (
    _FIELD_TYPE_MAP,
    _MODEL_CACHE_MAX_SIZE,
    _config_cache_key,
    _make_model_for_config,
    _model_cache,
    build_analysis_model,
)
from app.analysis.config import (
    _ALLOWED_FIELD_TYPES,
    _AXIS_NAME_RE,
    _BASE_AXIS_NAMES,
    _BASE_FIELD_NAMES,
    _KNOWN_BASE_AXES,
    AxisFieldDef,
    ExtractionConfig,
)
from app.analysis.enums import EngagementQuality, OutcomeClassification, Urgency
from app.analysis.prompts import (
    _AXIS_RULE_LINES,
    _BASE_RULES,
    _BASE_SYSTEM_INTRO,
    _UNIVERSAL_AXIS_INSTRUCTIONS,
    _universal_axis_order,
    ANALYSIS_SYSTEM_PROMPT,
    build_system_prompt,
)
from app.analysis.schema import PostCallAnalysis
from app.analysis.universal import (
    AbandonmentReasonAxis,
    CallOutcome,
    CommitmentSignalsAxis,
    DetectedInterests,
    IdentifiedProblem,
    ProfileFactsAxis,
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
    "ServiceIssuesAxis",
    "ProfileFactsAxis",
    "CommitmentSignalsAxis",
    "AbandonmentReasonAxis",
    "PostCallAnalysis",
    "ExtractionConfig",
    "AxisFieldDef",
    "ANALYSIS_SYSTEM_PROMPT",
    "build_system_prompt",
    "build_analysis_model",
    "UNIVERSAL_DIMENSIONS",
]
