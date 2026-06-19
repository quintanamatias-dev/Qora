"""Tests that _ensure_startup_schema_compat is removed from main.py.

Task 2.2 TDD — After PR 2 cutover:
  - _ensure_startup_schema_compat must NOT exist as an importable symbol in app.main
  - The lifespan must NOT call _ensure_startup_schema_compat

Spec scenario:
  - After removal, importing _ensure_startup_schema_compat from app.main raises ImportError
"""

from __future__ import annotations

import pytest


def test_ensure_startup_schema_compat_not_importable_from_main():
    """_ensure_startup_schema_compat must NOT exist in app.main after PR 2 cutover.

    GIVEN app.main has been updated (PR 2)
    WHEN _ensure_startup_schema_compat is imported from app.main
    THEN ImportError must be raised — function must be deleted

    This test serves as the gating check: if the function still exists,
    the test fails (RED → tells us the cutover is not complete).
    """
    with pytest.raises((ImportError, AttributeError)):
        from app.main import _ensure_startup_schema_compat  # noqa: F401


def test_ensure_startup_schema_compat_not_in_main_namespace():
    """app.main module must not expose _ensure_startup_schema_compat.

    GIVEN app.main is imported
    WHEN dir(app.main) is inspected
    THEN '_ensure_startup_schema_compat' must not be in the module namespace
    """
    import app.main as main_module

    assert "_ensure_startup_schema_compat" not in dir(main_module), (
        "_ensure_startup_schema_compat must be removed from app.main in PR 2. "
        "Schema compatibility is now handled by pre-start Alembic migration."
    )
