"""Interest pipeline catalog — thin re-export of the insurance vertical template.

PRODUCT_CATALOG/NEED_TAGS used to be this module's own authoritative lists.
Per-client catalogs are now resolved at runtime via
``app.tenants.revisions_service.resolve_client_catalog`` (analysis-profiles,
design.md P5). These module-level constants remain ONLY as a derived
re-export of ``app.analysis.profiles.templates.insurance`` — the single
source of truth is now that template, not this file (Gap B) — kept for
backward-compatible callers (tests, the insurance template's own drift-
detection test) that still read the literal Quintana/insurance id lists
directly.

Do NOT change these IDs here — change them in
``app.analysis.profiles.templates``'s ``_PRODUCT_IDS``/``_NEED_TAG_IDS``
instead; this module will reflect the change automatically.
"""

from __future__ import annotations

from app.analysis.profiles.templates import insurance as _insurance_template

PRODUCT_CATALOG: list[str] = [p.id for p in _insurance_template.config.products]
NEED_TAGS: list[str] = [n.id for n in _insurance_template.config.need_tags]
