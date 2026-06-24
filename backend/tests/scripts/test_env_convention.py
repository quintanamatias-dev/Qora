"""Tests for B8 env file convention: load_dotenv() paths resolve to repo root.

Spec reference:
  openspec/changes/phase-b-secrets-management/design.md — Decision: .env Source of Truth
  tasks.md 2.3 / 2.4

Design decision: Root .env is the single source of truth.
All load_dotenv() calls in app code must resolve OUTSIDE backend/,
i.e. the resolved path must be at the repo root (two levels above backend/app/).

Files validated:
  - backend/app/main.py
  - backend/scripts/seed_analysis_demo_call.py
  - backend/scripts/smoke_test_analysis.py
  - backend/scripts/check-secrets.py (new — already validated in test_check_secrets.py)

These are STRUCTURAL tests (source inspection) — they verify the convention
by reading the file contents, not by running the module.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_BACKEND_DIR = _REPO_ROOT / "backend"


def _read_source(relative_path: str) -> str:
    """Read a source file relative to the repo root."""
    path = _REPO_ROOT / relative_path
    assert path.exists(), f"Source file not found: {path}"
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Task 2.3 — RED tests: load_dotenv paths must resolve to repo root
# ---------------------------------------------------------------------------


class TestMainPyLoadDotenvPath:
    """backend/app/main.py load_dotenv() must resolve to repo root."""

    def test_main_py_load_dotenv_resolves_outside_backend(self):
        """main.py load_dotenv() path must NOT resolve to backend/.env.

        The path must resolve to <repo-root>/.env, which is THREE parents up
        from main.py (main.py → app/ → backend/ → repo-root/).
        Previously it was two parents (resolving to backend/.env).

        We detect this by asserting that .parent.parent.parent appears in the
        load_dotenv() call, or that the path uses 3 levels of .parent.
        """
        source = _read_source("backend/app/main.py")
        # The correct pattern: __file__.resolve().parent.parent.parent / ".env"
        # which resolves to repo-root/.env
        # Incorrect (old): __file__.resolve().parent.parent / ".env"
        # which resolves to backend/.env
        assert "parent.parent.parent" in source, (
            "backend/app/main.py load_dotenv() must resolve to repo-root/.env "
            "(three .parent levels from __file__: file → app/ → backend/ → root). "
            "Found only two .parent levels — still pointing at backend/.env. "
            "Update: load_dotenv(Path(__file__).resolve().parent.parent.parent / '.env', ...)"
        )

    def test_main_py_has_no_load_dotenv_pointing_at_backend_dot_env(self):
        """main.py must not contain a load_dotenv() call with only 2 parent levels.

        The old pattern 'parent.parent / \".env\"' resolved to backend/.env.
        After B8, it must use 'parent.parent.parent / \".env\"' for repo root.
        """
        source = _read_source("backend/app/main.py")
        # Find all load_dotenv(...) calls
        lines_with_load_dotenv = [
            line.strip()
            for line in source.splitlines()
            if "load_dotenv" in line and '".env"' in line
        ]
        # None of the load_dotenv lines should use exactly 2 parent traversals
        # (which would target backend/.env)
        for line in lines_with_load_dotenv:
            # Count occurrences of .parent in the line
            parent_count = line.count(".parent")
            # We want at least 3 parents (repo root is 3 levels above __file__ in app/)
            # 2 parents points to backend/.env (old behaviour — must be gone)
            assert parent_count != 2, (
                f"main.py load_dotenv() still uses exactly 2 .parent levels (backend/.env): {line}"
            )


class TestSeedScriptLoadDotenvPath:
    """backend/scripts/seed_analysis_demo_call.py load_dotenv() must resolve to repo root."""

    def test_seed_script_resolves_to_repo_root(self):
        """seed_analysis_demo_call.py must not load from backend/.env.

        The script is in backend/scripts/. Repo root is two parents up from the script:
        script → scripts/ → backend/ → repo-root/
        So it needs .parent.parent.parent (3 levels) from __file__,
        OR it can use BACKEND_DIR.parent / '.env'.
        """
        source = _read_source("backend/scripts/seed_analysis_demo_call.py")
        lines_with_load_dotenv = [
            line.strip()
            for line in source.splitlines()
            if "load_dotenv" in line
        ]
        assert lines_with_load_dotenv, "seed_analysis_demo_call.py has no load_dotenv() call"

        # Check that at least one load_dotenv references repo root:
        # Either BACKEND_DIR.parent / ".env" OR Path(...).parent.parent.parent / ".env"
        found_repo_root_path = any(
            "BACKEND_DIR.parent" in line or "parent.parent.parent" in line
            for line in lines_with_load_dotenv
        )
        assert found_repo_root_path, (
            "seed_analysis_demo_call.py load_dotenv() must point to repo-root/.env. "
            "Use: load_dotenv(BACKEND_DIR.parent / '.env') "
            f"Current load_dotenv lines: {lines_with_load_dotenv}"
        )

    def test_seed_script_does_not_load_backend_dot_env(self):
        """seed_analysis_demo_call.py must not use BACKEND_DIR / '.env' (resolves to backend/.env)."""
        source = _read_source("backend/scripts/seed_analysis_demo_call.py")
        # Old pattern: load_dotenv(BACKEND_DIR / ".env")
        # New pattern: load_dotenv(BACKEND_DIR.parent / ".env")
        assert 'BACKEND_DIR / ".env"' not in source and "BACKEND_DIR / '.env'" not in source, (
            "seed_analysis_demo_call.py still loads backend/.env via 'BACKEND_DIR / \".env\"'. "
            "Update to: load_dotenv(BACKEND_DIR.parent / '.env')"
        )


class TestSmokeTestLoadDotenvPath:
    """backend/scripts/smoke_test_analysis.py load_dotenv() must resolve to repo root."""

    def test_smoke_test_resolves_to_repo_root(self):
        """smoke_test_analysis.py must not load from backend/.env.

        The script is in backend/scripts/. Repo root needs 3 .parent levels from __file__.
        """
        source = _read_source("backend/scripts/smoke_test_analysis.py")
        lines_with_load_dotenv = [
            line.strip()
            for line in source.splitlines()
            if "load_dotenv" in line
        ]
        assert lines_with_load_dotenv, "smoke_test_analysis.py has no load_dotenv() call"

        # The load_dotenv path must include at least 3 parent traversals from __file__
        # (script → scripts/ → backend/ → repo-root/)
        found_repo_root_path = any(
            "parent.parent.parent" in line
            for line in lines_with_load_dotenv
        )
        assert found_repo_root_path, (
            "smoke_test_analysis.py load_dotenv() must use 3 .parent levels to reach repo root. "
            "Update to: load_dotenv(Path(__file__).resolve().parent.parent.parent / '.env') "
            f"Current load_dotenv lines: {lines_with_load_dotenv}"
        )

    def test_smoke_test_does_not_use_two_parents(self):
        """smoke_test_analysis.py must not use exactly 2 .parent levels (backend/.env path)."""
        source = _read_source("backend/scripts/smoke_test_analysis.py")
        lines_with_load_dotenv = [
            line.strip()
            for line in source.splitlines()
            if "load_dotenv" in line and '".env"' in line
        ]
        for line in lines_with_load_dotenv:
            parent_count = line.count(".parent")
            assert parent_count != 2, (
                f"smoke_test_analysis.py load_dotenv() still uses 2 .parent levels "
                f"(resolves to backend/.env): {line}"
            )


class TestCheckSecretsLoadDotenvPath:
    """backend/scripts/check-secrets.py (new script) must resolve to repo root."""

    def test_check_secrets_defaults_to_repo_root_env(self):
        """check-secrets.py default .env path must be repo-root/.env, not backend/.env."""
        source = _read_source("backend/scripts/check-secrets.py")
        # The script uses _REPO_ROOT / ".env" as the default env file
        assert '_REPO_ROOT / ".env"' in source or "_REPO_ROOT / '.env'" in source, (
            "check-secrets.py must use _REPO_ROOT / '.env' as the default env file path. "
            f"Current source excerpt around _DEFAULT_ENV_FILE: "
            f"{[l for l in source.splitlines() if '_DEFAULT_ENV_FILE' in l or '_REPO_ROOT' in l]}"
        )
