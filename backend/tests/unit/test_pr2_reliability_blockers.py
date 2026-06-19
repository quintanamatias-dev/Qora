"""Tests for PR2 reliability blockers — phase-b-db-migration-foundation.

Covers:
- Blocker 1a: qora_cli.py direct-DB entrypoints call run_migrations() before init_db()
- Blocker 1b: seed_analysis_demo_call.py calls run_migrations() before init_db()
- Blocker 3: Qora launcher (shell script) runs migrate.py before uvicorn (structural)

Strict TDD — these tests are written FIRST (RED) and then implementations are fixed.

Test strategy for Blockers 1a/1b:
    The async helpers import `db_module` and call `db_module.init_db()`.
    We inspect the AST / source text to verify run_migrations() is called
    before init_db() in each function, because:
    - Module-level import patching is brittle for scripts that re-import locally.
    - Source inspection is deterministic and does not require running real I/O.
    We supplement with a runtime call-order test that uses subprocess injection
    where feasible.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent  # backend/
QORA_CLI = BACKEND_DIR / "qora_cli.py"
SEED_SCRIPT = BACKEND_DIR / "scripts" / "seed_analysis_demo_call.py"
LAUNCHER_SCRIPT = BACKEND_DIR.parent / "Qora"  # repo root / Qora (bash)


# ===========================================================================
# Helpers
# ===========================================================================


def _function_body_lines(source: str, func_name: str) -> list[str]:
    """Return the source lines that make up a top-level async function body."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            if node.name == func_name:
                return ast.get_source_segment(source, node).splitlines()  # type: ignore[return-value]
    return []


def _find_call_positions(lines: list[str], *patterns: str) -> dict[str, int | None]:
    """Return {pattern: first_line_index_or_None} for each pattern in lines."""
    result: dict[str, int | None] = {p: None for p in patterns}
    for i, line in enumerate(lines):
        for p in patterns:
            if result[p] is None and p in line:
                result[p] = i
    return result


# ===========================================================================
# Blocker 1a: qora_cli.py — both DB-touching async helpers must call
# run_migrations() before init_db()
# ===========================================================================


class TestQoraCliMigratesBeforeInitDb:
    """qora_cli.py direct-DB entrypoints: migration must precede init_db.

    After PR2, init_db() no longer calls create_all(). Both _upsert_client_db
    and _list_clients_db must call run_migrations() from scripts/migrate.py
    BEFORE calling init_db() to guarantee schema exists on fresh DBs.
    """

    @pytest.fixture(autouse=True)
    def cli_source(self):
        self._source = QORA_CLI.read_text(encoding="utf-8")

    def _body_lines(self, func_name: str) -> list[str]:
        return _function_body_lines(self._source, func_name)

    # --- _upsert_client_db ---

    def test_upsert_client_db_contains_run_migrations_call(self):
        """_upsert_client_db body must reference run_migrations().

        GIVEN backend/qora_cli.py source
        WHEN _upsert_client_db body is extracted
        THEN it contains a call to run_migrations()
        """
        lines = self._body_lines("_upsert_client_db")
        assert lines, "_upsert_client_db not found in qora_cli.py"
        body = "\n".join(lines)
        assert "run_migrations" in body, (
            "_upsert_client_db does not call run_migrations(). "
            "It must call run_migrations() from scripts/migrate.py before init_db() "
            "to ensure the schema exists on fresh databases."
        )

    def test_upsert_client_db_run_migrations_before_init_db(self):
        """run_migrations() must appear before init_db() in _upsert_client_db.

        GIVEN backend/qora_cli.py source
        WHEN the positions of run_migrations and init_db calls are compared
        THEN run_migrations appears on an earlier line than init_db
        """
        lines = self._body_lines("_upsert_client_db")
        assert lines, "_upsert_client_db not found in qora_cli.py"
        pos = _find_call_positions(lines, "run_migrations", "init_db")

        assert pos["run_migrations"] is not None, (
            "_upsert_client_db does not call run_migrations()."
        )
        assert pos["init_db"] is not None, (
            "_upsert_client_db does not call init_db()."
        )
        assert pos["run_migrations"] < pos["init_db"], (
            f"run_migrations() at body-line {pos['run_migrations']}, "
            f"init_db() at body-line {pos['init_db']}. "
            "run_migrations MUST be called BEFORE init_db."
        )

    # --- _list_clients_db ---

    def test_list_clients_db_contains_run_migrations_call(self):
        """_list_clients_db body must reference run_migrations().

        GIVEN backend/qora_cli.py source
        WHEN _list_clients_db body is extracted
        THEN it contains a call to run_migrations()
        """
        lines = self._body_lines("_list_clients_db")
        assert lines, "_list_clients_db not found in qora_cli.py"
        body = "\n".join(lines)
        assert "run_migrations" in body, (
            "_list_clients_db does not call run_migrations(). "
            "It must call run_migrations() from scripts/migrate.py before init_db()."
        )

    def test_list_clients_db_run_migrations_before_init_db(self):
        """run_migrations() must appear before init_db() in _list_clients_db.

        GIVEN backend/qora_cli.py source
        WHEN the positions of run_migrations and init_db calls are compared
        THEN run_migrations appears on an earlier line than init_db
        """
        lines = self._body_lines("_list_clients_db")
        assert lines, "_list_clients_db not found in qora_cli.py"
        pos = _find_call_positions(lines, "run_migrations", "init_db")

        assert pos["run_migrations"] is not None, (
            "_list_clients_db does not call run_migrations()."
        )
        assert pos["init_db"] is not None, (
            "_list_clients_db does not call init_db()."
        )
        assert pos["run_migrations"] < pos["init_db"], (
            f"run_migrations() at body-line {pos['run_migrations']}, "
            f"init_db() at body-line {pos['init_db']}. "
            "run_migrations MUST be called BEFORE init_db."
        )


# ===========================================================================
# Blocker 1b: seed_analysis_demo_call.py — must call run_migrations() before
# init_db()
# ===========================================================================


class TestSeedAnalysisDemoCallMigratesBeforeInitDb:
    """seed_analysis_demo_call.py: migration must run before init_db.

    seed_demo_call() calls init_db() directly. After PR2, create_all() is gone,
    so seed_demo_call() must call run_migrations() first.
    """

    @pytest.fixture(autouse=True)
    def seed_source(self):
        self._source = SEED_SCRIPT.read_text(encoding="utf-8")

    def _body_lines(self, func_name: str) -> list[str]:
        return _function_body_lines(self._source, func_name)

    def test_seed_demo_call_contains_run_migrations_call(self):
        """seed_demo_call body must reference run_migrations().

        GIVEN backend/scripts/seed_analysis_demo_call.py source
        WHEN seed_demo_call body is extracted
        THEN it contains a call to run_migrations()
        """
        lines = self._body_lines("seed_demo_call")
        assert lines, "seed_demo_call not found in seed_analysis_demo_call.py"
        body = "\n".join(lines)
        assert "run_migrations" in body, (
            "seed_demo_call does not call run_migrations(). "
            "It must call run_migrations() from scripts/migrate.py before init_db() "
            "so fresh databases have the schema before any queries are run."
        )

    def test_seed_demo_call_run_migrations_before_init_db(self):
        """run_migrations() must appear before init_db() in seed_demo_call.

        GIVEN backend/scripts/seed_analysis_demo_call.py source
        WHEN the positions of run_migrations and init_db calls are compared
        THEN run_migrations appears on an earlier line than init_db
        """
        lines = self._body_lines("seed_demo_call")
        assert lines, "seed_demo_call not found in seed_analysis_demo_call.py"
        pos = _find_call_positions(lines, "run_migrations", "init_db")

        assert pos["run_migrations"] is not None, (
            "seed_demo_call does not call run_migrations()."
        )
        assert pos["init_db"] is not None, (
            "seed_demo_call does not call init_db()."
        )
        assert pos["run_migrations"] < pos["init_db"], (
            f"run_migrations() at body-line {pos['run_migrations']}, "
            f"init_db() at body-line {pos['init_db']}. "
            "run_migrations MUST be called BEFORE init_db."
        )


# ===========================================================================
# Blocker 3: Qora launcher ordering — migrate.py runs before uvicorn
# ===========================================================================


class TestQoraLauncherMigrationOrdering:
    """Verify the Qora bash launcher runs migrate.py before starting uvicorn.

    Structural tests: read the Qora shell script and verify:
    1. The script contains a call to scripts/migrate.py.
    2. That call appears BEFORE the uvicorn startup command.
    3. The migration call is blocking (not backgrounded with &).
    """

    @pytest.fixture(autouse=True)
    def launcher_content(self):
        assert LAUNCHER_SCRIPT.exists(), (
            f"Launcher script not found at {LAUNCHER_SCRIPT}. "
            "Expected Qora bash script at repo root."
        )
        self._content = LAUNCHER_SCRIPT.read_text(encoding="utf-8")
        self._lines = self._content.splitlines()

    def test_launcher_contains_migrate_call(self):
        """Qora script must reference scripts/migrate.py.

        GIVEN the Qora bash launcher script
        WHEN its text content is read
        THEN it contains a reference to migrate.py
        """
        assert "migrate.py" in self._content, (
            "Qora launcher does not reference migrate.py. "
            "The pre-start migration command must be present."
        )

    def test_launcher_migrate_before_uvicorn(self):
        """migrate.py call must appear BEFORE uvicorn in the Qora script.

        GIVEN the Qora bash launcher script
        WHEN the positions of migrate.py and uvicorn lines are compared
        THEN migrate.py appears on an earlier line than uvicorn app.main:app
        """
        migrate_line: int | None = None
        uvicorn_line: int | None = None

        for i, line in enumerate(self._lines):
            stripped = line.strip()
            if (
                not stripped.startswith("#")
                and "migrate.py" in stripped
                and migrate_line is None
            ):
                migrate_line = i
            if (
                not stripped.startswith("#")
                and "uvicorn" in stripped
                and "app.main:app" in stripped
                and "pgrep" not in stripped
                and "kill" not in stripped
                and uvicorn_line is None
            ):
                uvicorn_line = i

        assert migrate_line is not None, (
            "Could not find a migrate.py invocation line in the Qora launcher."
        )
        assert uvicorn_line is not None, (
            "Could not find a uvicorn app.main:app startup line in the Qora launcher."
        )
        assert migrate_line < uvicorn_line, (
            f"migrate.py at line {migrate_line + 1}, uvicorn at line {uvicorn_line + 1}. "
            "migrate.py MUST appear before uvicorn in the launcher script."
        )

    def test_launcher_migrate_call_is_blocking(self):
        """migrate.py call in the launcher must not be backgrounded with &.

        GIVEN the Qora bash launcher
        WHEN the migrate.py invocation line is inspected
        THEN it does NOT end with & (background operator)
        AND it is NOT launched via nohup
        """
        migrate_line_content: str | None = None
        for line in self._lines:
            stripped = line.strip()
            if not stripped.startswith("#") and "migrate.py" in stripped:
                migrate_line_content = stripped
                break

        assert migrate_line_content is not None, (
            "No migrate.py invocation found in Qora launcher."
        )

        code_part = migrate_line_content.split("#")[0].strip()
        assert not code_part.endswith("&"), (
            f"migrate.py invocation is backgrounded with '&': {migrate_line_content!r}. "
            "It MUST run synchronously (blocking) so the schema is ready before uvicorn starts."
        )
        assert "nohup" not in code_part, (
            f"migrate.py invocation uses nohup: {migrate_line_content!r}. "
            "It must run synchronously."
        )
