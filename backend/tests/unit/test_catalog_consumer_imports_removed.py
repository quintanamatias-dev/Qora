"""Phase 4.3 \u2014 static-import regression guard (design.md, tasks.md Phase 4).

leads/router.py and calls/router.py must resolve the product/need-tag
catalog via the client's own analysis profile (resolve_client_catalog), not
via a direct import of the fixed global PRODUCT_CATALOG/NEED_TAGS constants.
"""

from __future__ import annotations

from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_CONSUMER_FILES = [
    _BACKEND_DIR / "app" / "leads" / "router.py",
    _BACKEND_DIR / "app" / "calls" / "router.py",
]


def test_no_remaining_direct_catalog_import_in_consumers():
    for path in _CONSUMER_FILES:
        text = path.read_text(encoding="utf-8")
        assert "from app.analysis.universal.interest.catalog import" not in text, (
            f"{path} still directly imports from catalog.py \u2014 must resolve "
            "the per-client catalog via resolve_client_catalog instead"
        )
