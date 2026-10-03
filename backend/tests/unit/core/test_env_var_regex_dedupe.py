"""Task 7.1 — ALL_CAPS env-var-name regex must have exactly one definition.

Source-grep-based regression guard: the pattern literal ``[A-Z][A-Z0-9_]+``
must be a compiled regex object in exactly one module (app.core.credentials);
every other module imports the shared helper instead of redefining it.
"""

from __future__ import annotations

import re
from pathlib import Path

_APP_ROOT = Path(__file__).parent.parent.parent.parent / "app"

_COMPILED_PATTERN_LINE = re.compile(r"re\.compile\(r?[\"']\^\[A-Z\]\[A-Z0-9_\]\+\$?[\"']\)")


def _source_files() -> list[Path]:
    return [p for p in _APP_ROOT.rglob("*.py") if "__pycache__" not in p.parts]


def test_all_caps_regex_defined_in_exactly_one_module():
    matches: list[str] = []
    for path in _source_files():
        text = path.read_text(encoding="utf-8")
        if _COMPILED_PATTERN_LINE.search(text):
            matches.append(str(path.relative_to(_APP_ROOT.parent)))

    assert matches == ["app/core/credentials.py"], (
        "The ALL_CAPS env-var-name regex must be compiled in exactly one module "
        f"(app/core/credentials.py); found it compiled in: {matches}"
    )


def test_looks_like_env_var_name_helper_defined_in_exactly_one_module():
    def_pattern = re.compile(r"^def _looks_like_env_var_name\(", re.MULTILINE)
    matches: list[str] = []
    for path in _source_files():
        text = path.read_text(encoding="utf-8")
        if def_pattern.search(text):
            matches.append(str(path.relative_to(_APP_ROOT.parent)))

    assert matches == ["app/core/credentials.py"], (
        "_looks_like_env_var_name must be defined in exactly one module "
        f"(app/core/credentials.py); found it defined in: {matches}"
    )
