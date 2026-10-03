"""client-integrations-secrets Phase 4.6/5 — static-import regression guard.

No module under backend/app/ may import CRMConfigLoader. The class itself
still lives in crm_config.py (kept legacy, exercised directly by its own
unit tests) but every production reader — including crm_config_router.py
and leads/router.py, the two stragglers Phase 4 left for Phase 5 — now
reads through IntegrationStore instead.
"""

from __future__ import annotations

import re
from pathlib import Path

_APP_ROOT = Path(__file__).parent.parent.parent / "app"

# Matches actual import statements (`import CRMConfigLoader` / `CRMConfigLoader as x`),
# not incidental mentions of the name in comments or docstrings.
_IMPORT_PATTERN = re.compile(r"import\s+(?:[\w, ]*,\s*)?CRMConfigLoader\b")


def test_no_remaining_crm_config_loader_imports():
    """Every CRM config reader must read through IntegrationStore, not the
    filesystem CRMConfigLoader — zero imports anywhere under backend/app/.
    """
    offenders: list[str] = []
    for path in _APP_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if _IMPORT_PATTERN.search(text):
            offenders.append(str(path.relative_to(_APP_ROOT)))

    assert offenders == [], f"CRMConfigLoader must not be imported anywhere; found in: {offenders}"
