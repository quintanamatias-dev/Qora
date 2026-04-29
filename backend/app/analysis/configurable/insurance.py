"""Insurance-specific configurable axes — example of per-client extension.

The Lead model still owns ``current_insurance`` as a column populated through
conversation tools (``register_interest``). This module re-exposes it as an
AxisFieldDef so a future client config UI can opt back into LLM extraction by
appending it to ``ExtractionConfig.extra_axes`` for the insurance vertical
without polluting the universal schema.
"""

from __future__ import annotations

from app.analysis.config import AxisFieldDef

CURRENT_INSURANCE_FIELD = AxisFieldDef(
    name="current_insurance",
    field_type="str",
    description="Current insurance carrier the lead mentioned during the call, or null",
)
