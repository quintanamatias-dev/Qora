"""Backward-compatibility shim — the canonical home is now ``app.analysis``.

Existing imports of the form ``from app.analysis_schema import X`` continue to
work because every public symbol is re-exported from the package.
"""

from __future__ import annotations

from app.analysis import *  # noqa: F401,F403
from app.analysis import (  # noqa: F401  re-export private cache hooks used by tests
    _AXIS_NAME_RE,
    _AXIS_RULE_LINES,
    _ALLOWED_FIELD_TYPES,
    _BASE_AXIS_NAMES,
    _BASE_FIELD_NAMES,
    _BASE_RULES,
    _BASE_SYSTEM_INTRO,
    _FIELD_TYPE_MAP,
    _KNOWN_BASE_AXES,
    _MODEL_CACHE_MAX_SIZE,
    _UNIVERSAL_AXIS_INSTRUCTIONS,
    _config_cache_key,
    _make_model_for_config,
    _model_cache,
    _universal_axis_order,
)
