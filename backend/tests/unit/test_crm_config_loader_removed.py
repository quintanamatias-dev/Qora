"""client-integrations-secrets Phase 4.6 — static-import regression guard.

No CRM config reader under backend/app/ may import CRMConfigLoader except
crm_config.py itself (where it is defined) and the two files whose cutover
is explicitly out of scope for this phase:
  - app/integrations/crm_config_router.py — Phase 5 (router writes to DB)
  - app/leads/router.py — not enumerated among Phase 4's readers; tracked
    as a known gap for Phase 5/7 to pick up (see Phase 4 handoff notes).
"""

from __future__ import annotations

import re
from pathlib import Path

_APP_ROOT = Path(__file__).parent.parent.parent / "app"

_ALLOWED_IMPORTERS = frozenset(
    {
        "integrations/crm_config.py",
        "integrations/crm_config_router.py",
        "leads/router.py",
    }
)

# Matches actual import statements (`import CRMConfigLoader` / `CRMConfigLoader as x`),
# not incidental mentions of the name in comments or docstrings.
_IMPORT_PATTERN = re.compile(r"import\s+(?:[\w, ]*,\s*)?CRMConfigLoader\b")


def test_no_remaining_crm_config_loader_imports():
    """Every CRM config reader must read through IntegrationStore, not the
    filesystem CRMConfigLoader — except the explicitly allowed stragglers.
    """
    offenders: list[str] = []
    for path in _APP_ROOT.rglob("*.py"):
        rel = str(path.relative_to(_APP_ROOT))
        if rel in _ALLOWED_IMPORTERS:
            continue
        text = path.read_text(encoding="utf-8")
        if _IMPORT_PATTERN.search(text):
            offenders.append(rel)

    assert offenders == [], (
        f"CRMConfigLoader must not be imported outside {_ALLOWED_IMPORTERS}; "
        f"found in: {offenders}"
    )
