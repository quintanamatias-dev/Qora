"""Backward-compatibility shim — the canonical home is now ``app.analysis``.

Existing imports of the form ``from app.analysis_schema import X`` continue to
work for the per-dimension universal axes and the composite ``PostCallAnalysis``
root model. Legacy items (``ANALYSIS_SYSTEM_PROMPT``, ``build_system_prompt``,
``ExtractionConfig``, ``AxisFieldDef``, ``build_analysis_model``) were removed
when the analysis pipeline switched to per-dimension self-contained modules.
"""

from __future__ import annotations

from app.analysis import *  # noqa: F401,F403
