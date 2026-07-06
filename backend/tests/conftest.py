"""Pytest configuration and shared fixtures for QORA backend tests.

Provides:
- Async SQLite engine (isolated per test, schema created via Alembic migrations)
- App factory with QORA lifespan
- QORA Settings fixture (no Twilio dependencies)
- respx mocks for OpenAI/ElevenLabs
- Auth fixtures (Phase B5): auth_headers + QORA_API_KEY env injection
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Auth test configuration (Phase B5 — PR #1: Foundation + Admin Auth)
# ---------------------------------------------------------------------------
# A well-known test API key used by all backend tests. Never used in production.
# This value is intentionally public — it only authenticates against the ephemeral
# in-process test server, never against a real QORA deployment.
# ---------------------------------------------------------------------------

_TEST_API_KEY = "qora-test-key-do-not-use-in-production"


# ---------------------------------------------------------------------------
# Backup gate bypass for test environments
# ---------------------------------------------------------------------------
# scripts/migrate.py requires a today's backup before touching any existing DB
# (spec: Baseline Backup and Verification). Test environments use ephemeral
# tmp_path DBs with no real data, so the backup gate must be bypassed globally.
# Production workflows and the smoke_stamped_db fixture set this explicitly.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _skip_backup_check_in_tests(monkeypatch):
    """Bypass the migrate.py backup gate for all tests.

    Test DBs are ephemeral (tmp_path) and never need a backup. Without this,
    any test that calls run_migrations() against an existing DB path would
    receive sys.exit(1) because no today's backup exists at the tmp_path.
    """
    monkeypatch.setenv("QORA_SKIP_BACKUP_CHECK", "1")


# ---------------------------------------------------------------------------
# Session store isolation — VSC-8 Fix A
# ---------------------------------------------------------------------------
# The module-level session_store singleton is shared across all tests in a process.
# Without cleanup between tests, find_by_client_lead() can find leftover sessions
# from earlier tests and skip creating new DB sessions — breaking tests that expect
# a new CallSession to be created on every request.
#
# This autouse fixture clears the singleton before every test automatically.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_session_store_between_tests():
    """Clear the global session_store before each test to prevent state leakage."""
    from app.voice.session import session_store

    session_store._sessions.clear()
    yield
    session_store._sessions.clear()


# ---------------------------------------------------------------------------
# Auth fixtures (Phase B5 — PR #1: Foundation + Admin Auth)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _inject_test_api_key(monkeypatch):
    """Inject QORA_API_KEY into the test process environment.

    This ensures that any Settings() instance created during tests (e.g. in
    route dependencies that fall back to Settings() when app.state.settings
    is not populated) will find a valid API key without per-test changes.

    The key value is intentionally a known test constant — it only
    authenticates against the in-process test server.
    """
    monkeypatch.setenv("QORA_API_KEY", _TEST_API_KEY)


@pytest.fixture(autouse=True, scope="session")
def _disable_webhook_auth_in_tests():
    """Disable webhook auth for all tests.

    The project .env may have QORA_WEBHOOK_AUTH_ENABLED=true for production use,
    but tests do not send X-Webhook-Secret headers (original design intent).
    Setting this to false restores the original open test behavior.

    Tests that need to verify webhook auth enforcement must override
    QORA_WEBHOOK_AUTH_ENABLED via their own monkeypatch/env setup — see
    test_webhook_auth_cors.py and test_fail_closed_outbound_webhook_auth.py.
    """
    import os

    original = os.environ.get("QORA_WEBHOOK_AUTH_ENABLED")
    os.environ["QORA_WEBHOOK_AUTH_ENABLED"] = "false"
    yield
    if original is None:
        os.environ.pop("QORA_WEBHOOK_AUTH_ENABLED", None)
    else:
        os.environ["QORA_WEBHOOK_AUTH_ENABLED"] = original


@pytest.fixture(autouse=True)
def _disable_outbound_calls_in_tests(monkeypatch):
    """Force ENABLE_OUTBOUND_CALLS=false for the test environment.

    The project .env may have ENABLE_OUTBOUND_CALLS=true (production dev config).
    Any Settings() construction in tests that does not explicitly pass
    enable_outbound_calls=False would trigger the fail-closed validator that
    requires QORA_WEBHOOK_AUTH_ENABLED=true whenever outbound is enabled.

    Tests that need to exercise the outbound+webhook-auth combination must
    override ENABLE_OUTBOUND_CALLS and QORA_WEBHOOK_AUTH_ENABLED explicitly
    in their own env setup (see test_fail_closed_outbound_webhook_auth.py for
    the pattern).

    This fixture prevents the test suite from being broken by a production .env
    value that is correct for production but unsafe for the test sandbox.
    """
    monkeypatch.setenv("ENABLE_OUTBOUND_CALLS", "false")


@pytest.fixture(autouse=True)
def _auto_bypass_api_key(request):
    """Autouse fixture: bypass require_api_key for all tests except auth behavior tests.

    Sets app.core.auth._TESTING_BYPASS = True so that require_api_key() returns a
    synthetic CallerIdentity without checking the Authorization header. This prevents
    ~1724 existing tests from failing with 401 after admin routes were protected.

    Tests in TestAdminRoutesRequireAuth are excluded — they explicitly verify that
    401 is returned when the real auth dependency runs without a valid header.

    The bypass flag only activates when running under pytest (PYTEST_CURRENT_TEST
    env var is set by pytest itself). Production processes never set this flag.
    """
    import app.core.auth as auth_module

    # Tests in test_auth.py that verify real auth behavior must NOT get the bypass.
    # Identified by their class names — all classes in that module test real auth.
    _AUTH_TEST_CLASSES = {"TestRequireApiKey", "TestAuthSettings", "TestAdminRoutesRequireAuth"}
    cls = request.node.cls
    if cls is not None and cls.__name__ in _AUTH_TEST_CLASSES:
        # Ensure bypass is OFF for these tests
        auth_module._TESTING_BYPASS = False
        yield
        auth_module._TESTING_BYPASS = False
        return

    # Enable bypass for all other tests
    auth_module._TESTING_BYPASS = True
    yield
    auth_module._TESTING_BYPASS = False


@pytest.fixture
def bypass_api_key():
    """Explicit opt-in bypass marker — no-op since autouse handles it."""
    pass


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Return HTTP headers that satisfy require_api_key for the test key.

    Usage in test functions that need to test real auth behavior
    (e.g. TestAdminRoutesRequireAuth which clears dependency_overrides):
        response = client.get("/api/v1/clients", headers=auth_headers)

    Usage with httpx AsyncClient:
        response = await async_client.get("/api/v1/clients", headers=auth_headers)
    """
    return {"Authorization": f"Bearer {_TEST_API_KEY}"}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@pytest.fixture
def test_settings(tmp_path: Path):
    """Create QORA Settings pointing at an isolated SQLite file."""
    from app.core.config import Settings

    db_url = f"sqlite+aiosqlite:///{tmp_path}/qora_test.db"
    return Settings(
        openai_api_key=SecretStr("sk-test-openai"),
        elevenlabs_api_key=SecretStr("el-test-key"),
        qora_api_key=SecretStr(_TEST_API_KEY),
        database_url=db_url,
        debug=False,
    )


# ---------------------------------------------------------------------------
# Database engine
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_engine(test_settings):
    """Async SQLite engine with all QORA tables created via Alembic migrations.

    Uses apply_migrations() instead of Base.metadata.create_all() so that
    test DBs follow the production schema path and catch migration drift.

    Design: phase-b-db-migration-foundation/design.md — Test DB creation decision.
    """
    from app.core import database as db_module
    from tests.helpers.migrations import apply_migrations

    # 1. Run Alembic upgrade head — creates schema and stamps alembic_version
    apply_migrations(test_settings.database_url)

    # 2. Initialize the async engine and session factory (no DDL — schema already exists)
    db_module.create_engine_and_session(test_settings.database_url)

    # 3. Register all ORM models with Base.metadata (required for session queries)
    import app.tenants.models  # noqa: F401
    import app.leads.models  # noqa: F401
    import app.calls.models  # noqa: F401
    import app.scheduler.models  # noqa: F401
    import app.jobs.models  # noqa: F401  — BackgroundJob model (Phase B10)

    # 4. Enable WAL mode for concurrent read/write support (matches production init_db)
    from sqlalchemy import text
    async with db_module.engine.connect() as raw_conn:  # type: ignore[union-attr]
        await raw_conn.execute(text("PRAGMA journal_mode=WAL"))
        await raw_conn.execute(text("PRAGMA busy_timeout=5000"))
        await raw_conn.commit()

    yield db_module
    await db_module.close_db()


@pytest_asyncio.fixture
async def db_session(test_settings, db_engine):
    """Yield a single async session for a test. Auto-commits on success."""
    assert db_engine.async_session_factory is not None, "DB not initialized"
    async with db_engine.async_session_factory() as session:
        yield session


# ---------------------------------------------------------------------------
# OpenAI streaming mock (SSE)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_openai_stream():
    """Return a factory for fake OpenAI SSE chunks."""

    def make_stream(tokens: list[str]):
        """Yield fake SSE chunk objects for each token."""

        async def _gen():
            for token in tokens:
                chunk = MagicMock()
                chunk.choices = [MagicMock()]
                chunk.choices[0].delta.content = token
                chunk.choices[0].delta.tool_calls = None
                chunk.choices[0].finish_reason = None
                yield chunk
            # Final chunk with finish_reason
            done_chunk = MagicMock()
            done_chunk.choices = [MagicMock()]
            done_chunk.choices[0].delta.content = None
            done_chunk.choices[0].delta.tool_calls = None
            done_chunk.choices[0].finish_reason = "stop"
            yield done_chunk

        return _gen()

    return make_stream
