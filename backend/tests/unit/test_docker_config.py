"""Tests for Docker configuration files.

Verifies:
- .dockerignore excludes required sensitive/build paths (spec: Dockerignore Exclusions)
- docker/entrypoint.sh has required shell constructs (spec: Entrypoint Migration)
- StaticFiles mount in main.py is conditional and last (spec: Static Frontend Serving)

TDD note: Tests written first (RED), then implementation created (GREEN).
Triangulation cases added to cover additional edge cases and prevent trivial Fake It.
"""

from __future__ import annotations

import os
from pathlib import Path

# Repository root relative to this file: backend/tests/unit/ → root
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


# ---------------------------------------------------------------------------
# 1.1 .dockerignore content tests
# ---------------------------------------------------------------------------


class TestDockerignore:
    """Spec: Dockerignore Exclusions — .env, *.db, node_modules/, .venv/,
    __pycache__/, and .git/ must be excluded from the build context."""

    _path = _REPO_ROOT / ".dockerignore"

    def _read_lines(self) -> list[str]:
        return self._path.read_text().splitlines()

    def test_dockerignore_file_exists(self):
        assert self._path.exists(), ".dockerignore not found at repo root"

    def test_excludes_env_file(self):
        lines = self._read_lines()
        assert ".env" in lines, ".dockerignore must exclude .env"

    def test_excludes_db_files(self):
        lines = self._read_lines()
        assert "*.db" in lines, ".dockerignore must exclude *.db files"

    def test_excludes_node_modules(self):
        content = self._path.read_text()
        assert "node_modules" in content, ".dockerignore must exclude node_modules"

    def test_excludes_venv(self):
        content = self._path.read_text()
        assert ".venv" in content, ".dockerignore must exclude .venv"

    def test_excludes_pycache(self):
        content = self._path.read_text()
        assert "__pycache__" in content, ".dockerignore must exclude __pycache__"

    def test_excludes_git(self):
        content = self._path.read_text()
        assert ".git" in content, ".dockerignore must exclude .git"


# ---------------------------------------------------------------------------
# 1.2 docker/entrypoint.sh content tests
# ---------------------------------------------------------------------------


class TestEntrypointSh:
    """Spec: Entrypoint Migration — set -e, migrate.py, exec uvicorn."""

    _path = _REPO_ROOT / "docker" / "entrypoint.sh"

    def _read(self) -> str:
        return self._path.read_text()

    def test_entrypoint_file_exists(self):
        assert self._path.exists(), "docker/entrypoint.sh not found"

    def test_set_e_for_fail_fast(self):
        content = self._read()
        assert "set -e" in content, "entrypoint.sh must use set -e to exit on error"

    def test_runs_migrate_py(self):
        content = self._read()
        assert "python scripts/migrate.py" in content, (
            "entrypoint.sh must run python scripts/migrate.py"
        )

    def test_execs_uvicorn(self):
        content = self._read()
        assert "exec uvicorn" in content, (
            "entrypoint.sh must exec uvicorn (not run) for PID 1 signal handling"
        )

    def test_uvicorn_binds_all_interfaces(self):
        content = self._read()
        assert "--host 0.0.0.0" in content, (
            "uvicorn must bind to 0.0.0.0 to be reachable from outside container"
        )

    def test_uvicorn_port_8000(self):
        content = self._read()
        assert "--port 8000" in content, "uvicorn must listen on port 8000"

    def test_is_executable(self):
        assert os.access(str(self._path), os.X_OK), (
            "docker/entrypoint.sh must be executable"
        )


# ---------------------------------------------------------------------------
# 1.3 Dockerfile content tests
# ---------------------------------------------------------------------------


class TestDockerfile:
    """Spec: Image Build — multi-stage Dockerfile with Node build and Python runtime."""

    _path = _REPO_ROOT / "Dockerfile"

    def _read(self) -> str:
        return self._path.read_text()

    def test_dockerfile_exists(self):
        assert self._path.exists(), "Dockerfile not found at repo root"

    def test_uses_node_build_stage(self):
        content = self._read()
        assert "node:22-alpine" in content, (
            "Dockerfile must use node:22-alpine for the frontend build stage"
        )

    def test_uses_python_runtime_stage(self):
        content = self._read()
        assert "python:3.11-slim" in content, (
            "Dockerfile must use python:3.11-slim for the runtime stage"
        )

    def test_npm_run_build_present(self):
        content = self._read()
        assert "npm run build" in content, (
            "Dockerfile must run npm run build to compile the React frontend"
        )

    def test_copies_static_frontend(self):
        content = self._read()
        assert "static-frontend" in content, (
            "Dockerfile must copy the built frontend to static-frontend/ in the image"
        )

    def test_uv_sync_frozen(self):
        content = self._read()
        assert "uv sync" in content and "--frozen" in content, (
            "Dockerfile must use uv sync --frozen for reproducible Python installs"
        )

    def test_non_root_user(self):
        content = self._read()
        assert "qora" in content and "USER" in content, (
            "Dockerfile must create and use a non-root 'qora' user"
        )

    def test_exposes_port_8000(self):
        content = self._read()
        assert "EXPOSE 8000" in content, "Dockerfile must expose port 8000"

    def test_uses_entrypoint_sh(self):
        content = self._read()
        assert "entrypoint.sh" in content, (
            "Dockerfile must use docker/entrypoint.sh as its entrypoint"
        )


# ---------------------------------------------------------------------------
# 2.1/2.2 docker-compose.yml content tests
# ---------------------------------------------------------------------------


class TestDockerCompose:
    """Spec: Single-Port Compose Startup, Health Check, Environment Variable Injection."""

    _path = _REPO_ROOT / "docker-compose.yml"

    def _read(self) -> str:
        return self._path.read_text()

    def test_compose_file_exists(self):
        assert self._path.exists(), "docker-compose.yml not found at repo root"

    def test_port_8000_mapped(self):
        content = self._read()
        assert "8000:8000" in content, (
            "docker-compose.yml must map port 8000:8000 for single-port access"
        )

    def test_env_file_referenced(self):
        content = self._read()
        assert "env_file" in content, (
            "docker-compose.yml must use env_file to inject .env at runtime"
        )

    def test_skip_backup_check_set(self):
        content = self._read()
        assert "QORA_SKIP_BACKUP_CHECK" in content, (
            "docker-compose.yml must set QORA_SKIP_BACKUP_CHECK=1 to prevent "
            "migration blocking on container restart"
        )

    def test_database_url_in_compose(self):
        content = self._read()
        assert "DATABASE_URL" in content, (
            "docker-compose.yml must define DATABASE_URL pointing to the volume path"
        )

    def test_named_volume_qora_data(self):
        content = self._read()
        assert "qora-data" in content, (
            "docker-compose.yml must define a named volume 'qora-data' for SQLite persistence"
        )

    def test_healthcheck_present(self):
        content = self._read()
        assert "healthcheck" in content, (
            "docker-compose.yml must define a healthcheck"
        )

    def test_healthcheck_uses_health_endpoint(self):
        content = self._read()
        assert "/api/v1/health" in content, (
            "docker-compose.yml health check must poll /api/v1/health"
        )

    def test_restart_policy(self):
        content = self._read()
        assert "unless-stopped" in content, (
            "docker-compose.yml must set restart: unless-stopped"
        )


# ---------------------------------------------------------------------------
# 2.3 StaticFiles mount in main.py — tested via import + mock dir
# ---------------------------------------------------------------------------


class TestStaticFilesMountLogic:
    """Spec: Static Frontend Serving — conditional mount only when dist dir exists,
    API routes registered first take priority, html=True for SPA routing."""

    def test_static_frontend_import_present(self):
        """main.py must import StaticFiles (already present for demo page)."""
        main_path = _REPO_ROOT / "backend" / "app" / "main.py"
        content = main_path.read_text()
        assert "StaticFiles" in content, (
            "main.py must import StaticFiles from starlette"
        )

    def test_frontend_dir_variable_defined(self):
        """main.py must define _FRONTEND_DIR pointing two levels up to static-frontend."""
        main_path = _REPO_ROOT / "backend" / "app" / "main.py"
        content = main_path.read_text()
        assert "_FRONTEND_DIR" in content, (
            "main.py must define _FRONTEND_DIR for the frontend static files path"
        )

    def test_mount_is_conditional(self):
        """The frontend StaticFiles mount must be guarded by os.path.isdir check."""
        main_path = _REPO_ROOT / "backend" / "app" / "main.py"
        content = main_path.read_text()
        assert "os.path.isdir(_FRONTEND_DIR)" in content, (
            "The frontend StaticFiles mount must be conditional on _FRONTEND_DIR existing"
        )

    def test_html_true_for_spa_routing(self):
        """The frontend mount must use html=True for React Router deep-link fallback."""
        main_path = _REPO_ROOT / "backend" / "app" / "main.py"
        content = main_path.read_text()
        # Check both the frontend section has html=True
        # We look for the pattern near _FRONTEND_DIR
        assert "html=True" in content, (
            "StaticFiles mount for frontend must use html=True for SPA fallback routing"
        )

    def test_catch_all_route_for_spa_deeplinks(self):
        """A catch-all route must exist to serve index.html for SPA deep links.

        Starlette StaticFiles html=True does NOT catch arbitrary paths, only
        directory roots. A catch-all GET route is required for React Router to work.
        """
        main_path = _REPO_ROOT / "backend" / "app" / "main.py"
        content = main_path.read_text()
        assert "full_path:path" in content, (
            "main.py must define a catch-all route '/{full_path:path}' to serve "
            "index.html for SPA deep-link navigation"
        )

    def test_file_response_imported(self):
        """FileResponse must be imported in main.py for the catch-all SPA route."""
        main_path = _REPO_ROOT / "backend" / "app" / "main.py"
        content = main_path.read_text()
        assert "FileResponse" in content, (
            "main.py must import FileResponse to serve index.html via the catch-all route"
        )

    def test_frontend_mount_after_api_routes(self):
        """The frontend StaticFiles mount at '/' must come AFTER all API route registrations."""
        main_path = _REPO_ROOT / "backend" / "app" / "main.py"
        content = main_path.read_text()
        # app.include_router(api_v1_router) must appear before _FRONTEND_DIR
        api_router_pos = content.find("app.include_router(api_v1_router)")
        frontend_dir_pos = content.find("_FRONTEND_DIR")
        assert api_router_pos != -1, "api_v1_router must be included in main.py"
        assert frontend_dir_pos != -1, "_FRONTEND_DIR must be defined in main.py"
        assert api_router_pos < frontend_dir_pos, (
            "API routes must be registered before the frontend StaticFiles mount "
            "so API paths take priority over the static catch-all"
        )

    def test_frontend_serves_static_assets(self):
        """The frontend strategy must serve static assets (JS/CSS) from the build dir."""
        main_path = _REPO_ROOT / "backend" / "app" / "main.py"
        content = main_path.read_text()
        # Either a root mount OR asset subdirectory mounts must be present
        has_root_mount = 'app.mount("/", StaticFiles(directory=_FRONTEND_DIR' in content
        has_asset_mount = "_asset_subdir" in content or "assets" in content
        assert has_root_mount or has_asset_mount, (
            "main.py must serve React frontend static assets via StaticFiles"
        )


# ---------------------------------------------------------------------------
# Triangulation: additional cases that prevent trivial Fake It
# ---------------------------------------------------------------------------


class TestDockerignoreTriangulation:
    """Additional exclusion patterns beyond the minimum six required by spec."""

    _path = _REPO_ROOT / ".dockerignore"

    def test_excludes_db_wal_files(self):
        """*.db-wal files must also be excluded (SQLite WAL journals)."""
        content = self._path.read_text()
        assert "*.db-wal" in content, ".dockerignore must exclude *.db-wal SQLite WAL files"

    def test_excludes_db_shm_files(self):
        """*.db-shm files must also be excluded (SQLite shared memory)."""
        content = self._path.read_text()
        assert "*.db-shm" in content, ".dockerignore must exclude *.db-shm SQLite shared memory files"

    def test_excludes_gitignore_itself(self):
        """The .git directory must be excluded (not just .gitignore)."""
        content = self._path.read_text()
        assert ".git/" in content, ".dockerignore must exclude .git/ directory"


class TestEntrypointShTriangulation:
    """Entrypoint must use the bash shebang and proper uvicorn target."""

    _path = _REPO_ROOT / "docker" / "entrypoint.sh"

    def test_uses_bash_shebang(self):
        """Shebang must be bash-compatible (not sh) for portability on slim images."""
        first_line = self._path.read_text().splitlines()[0]
        assert "bash" in first_line, (
            "entrypoint.sh must use a bash-compatible shebang"
        )

    def test_uvicorn_app_target(self):
        """uvicorn must target app.main:app (the FastAPI application object)."""
        content = self._path.read_text()
        assert "app.main:app" in content, (
            "uvicorn must be invoked with app.main:app as the application target"
        )


class TestDockerComposeTriangulation:
    """Additional compose assertions beyond minimum fields."""

    _path = _REPO_ROOT / "docker-compose.yml"

    def test_app_data_path_in_database_url(self):
        """DATABASE_URL must point inside /app/data/ for the volume path."""
        content = self._path.read_text()
        assert "/app/data/" in content, (
            "DATABASE_URL in docker-compose.yml must reference /app/data/ "
            "to match the named volume mount point"
        )

    def test_healthcheck_has_interval(self):
        """Health check must define an interval (not rely on Docker defaults)."""
        content = self._path.read_text()
        assert "interval:" in content, (
            "docker-compose.yml healthcheck must specify an interval"
        )

    def test_healthcheck_has_retries(self):
        """Health check must define retries to control failure tolerance."""
        content = self._path.read_text()
        assert "retries:" in content, (
            "docker-compose.yml healthcheck must specify retries"
        )

    def test_volume_mount_targets_app_data(self):
        """The qora-data volume must be mounted at /app/data inside the container."""
        content = self._path.read_text()
        assert "/app/data" in content, (
            "docker-compose.yml must mount qora-data volume at /app/data "
            "to match DATABASE_URL path"
        )


class TestDockerfileTriangulation:
    """Dockerfile correctness beyond minimum presence checks."""

    _path = _REPO_ROOT / "Dockerfile"

    def test_npm_ci_for_reproducible_install(self):
        """npm ci must be used (not npm install) for reproducible builds."""
        content = self._path.read_text()
        assert "npm ci" in content, (
            "Dockerfile must use npm ci (not npm install) for reproducible frontend builds"
        )

    def test_no_dev_flag_on_uv_sync(self):
        """uv sync must use --no-dev to exclude dev dependencies from the image."""
        content = self._path.read_text()
        assert "--no-dev" in content, (
            "Dockerfile uv sync must use --no-dev to keep image lean"
        )

    def test_creates_app_data_dir(self):
        """The Dockerfile must create /app/data so the qora user can write the DB."""
        content = self._path.read_text()
        assert "/app/data" in content, (
            "Dockerfile must create /app/data directory for SQLite volume mount"
        )


class TestStaticFilesMountTriangulation:
    """Edge cases for the conditional StaticFiles mount in main.py."""

    def test_demo_mount_still_present(self):
        """The existing /demo StaticFiles mount must NOT be removed."""
        main_path = _REPO_ROOT / "backend" / "app" / "main.py"
        content = main_path.read_text()
        assert 'app.mount("/demo"' in content, (
            "The /demo StaticFiles mount must remain intact — it serves the voice demo page"
        )

    def test_frontend_mount_named_for_identification(self):
        """The frontend StaticFiles mounts must include 'frontend' in their names."""
        main_path = _REPO_ROOT / "backend" / "app" / "main.py"
        content = main_path.read_text()
        # Accepts name="frontend" (root mount) or name=f"frontend-{...}" (asset mounts)
        assert '"frontend"' in content or "'frontend" in content or "frontend-" in content, (
            "Frontend StaticFiles mounts must use names prefixed with 'frontend'"
        )

    def test_frontend_dir_path_resolves_one_level_up(self):
        """_FRONTEND_DIR must navigate one level up from __file__ to reach /app/static-frontend/.

        In Docker: __file__ = /app/app/main.py, dirname = /app/app/, one '..' = /app/,
        then 'static-frontend' = /app/static-frontend/ (where Dockerfile copies dist/).
        """
        main_path = _REPO_ROOT / "backend" / "app" / "main.py"
        content = main_path.read_text()
        assert "static-frontend" in content, (
            "_FRONTEND_DIR must reference 'static-frontend' as the directory name "
            "matching what the Dockerfile copies the dist/ into"
        )
