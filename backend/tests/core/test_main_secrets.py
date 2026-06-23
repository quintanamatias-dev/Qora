"""Tests for Phase B8 — Secrets Management: main.py integration behavior.

Covers:
  1. main.py reads QORA_DOCS_ENABLED and QORA_ALLOWED_ORIGINS via settings.*,
     not via direct os.getenv() calls for these declared Settings vars.
  2. The lifespan startup ACTUALLY CALLS validate_all_integration_credentials()
     (behavior-level test — enters the lifespan context and asserts the mock).
  3. Negative: lifespan raises SystemExit when validate_all_integration_credentials
     reports invalid/missing active CRM credentials.

Spec reference:
  secrets-validation/spec.md — Requirement: Settings as Sole Env Authority
  tenant-integration-secrets/spec.md — Requirement: Startup Validation for Configured Integrations

Design reference:
  design.md — Data Flow diagram (lifespan calls validate_all_integration_credentials)

Test strategy:
  - Source-inspection tests: assert os.getenv() is not used for declared Settings vars
    (guard against regression of the B8 env-authority fix).
  - Behavior tests: enter lifespan() directly via async context manager, patch
    validate_all_integration_credentials and all heavy I/O (DB, seed, sweeper),
    and assert mock.called is True. No source-text checks substitute for this.
  - Negative behavior test: side_effect=SystemExit on the validator mock verifies
    that startup propagates the failure before the yield (before requests are served).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MAIN_PY = Path(__file__).parent.parent.parent / "app" / "main.py"


def _get_main_source() -> str:
    return _MAIN_PY.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Shared lifespan fixture
# ---------------------------------------------------------------------------


def _make_mock_settings() -> MagicMock:
    """Return a MagicMock that satisfies the attributes lifespan() reads."""
    mock = MagicMock()
    mock.log_level = "INFO"
    mock.host = "0.0.0.0"
    mock.port = 8000
    mock.database_url = "sqlite+aiosqlite:///./test.db"
    return mock


def _make_mock_session() -> AsyncMock:
    """Return an async context manager mock for the DB session factory."""
    sess = AsyncMock()
    sess.__aenter__ = AsyncMock(return_value=sess)
    sess.__aexit__ = AsyncMock(return_value=None)
    return sess


# ---------------------------------------------------------------------------
# Task 1.7 — Settings as sole env authority in main.py (source-inspection)
# ---------------------------------------------------------------------------


class TestMainPyNoOsGetenvBypasses:
    """main.py must not use os.getenv() for vars declared in Settings."""

    def test_qora_docs_enabled_not_read_via_os_getenv(self):
        """QORA_DOCS_ENABLED must NOT appear in an os.getenv() call in main.py.

        It must be read from settings.qora_docs_enabled instead.
        Spec: secrets-validation — Requirement: Settings as Sole Env Authority
        """
        source = _get_main_source()
        assert 'os.getenv("QORA_DOCS_ENABLED"' not in source, (
            'main.py must not call os.getenv("QORA_DOCS_ENABLED"). '
            "Read from settings.qora_docs_enabled instead."
        )
        assert "os.getenv('QORA_DOCS_ENABLED'" not in source, (
            "main.py must not call os.getenv('QORA_DOCS_ENABLED'). "
            "Read from settings.qora_docs_enabled instead."
        )

    def test_qora_allowed_origins_not_read_via_os_getenv(self):
        """QORA_ALLOWED_ORIGINS must NOT appear in an os.getenv() call in main.py.

        It must be read from settings.qora_allowed_origins instead.
        Spec: secrets-validation — Requirement: Settings as Sole Env Authority
        """
        source = _get_main_source()
        assert 'os.getenv("QORA_ALLOWED_ORIGINS"' not in source, (
            'main.py must not call os.getenv("QORA_ALLOWED_ORIGINS"). '
            "Read from settings.qora_allowed_origins instead."
        )
        assert "os.getenv('QORA_ALLOWED_ORIGINS'" not in source, (
            "main.py must not call os.getenv('QORA_ALLOWED_ORIGINS'). "
            "Read from settings.qora_allowed_origins instead."
        )

    def test_create_app_reads_docs_from_settings(self):
        """create_app() must use settings.qora_docs_enabled for the docs toggle.

        This is a structural check: the Settings instance must be the source of
        docs_enabled, not a direct env lookup.
        """
        source = _get_main_source()
        assert "settings.qora_docs_enabled" in source or "qora_docs_enabled" in source, (
            "create_app() must read qora_docs_enabled from a Settings instance."
        )

    def test_cors_origins_read_from_settings(self):
        """CORS middleware must use settings.qora_allowed_origins, not os.getenv()."""
        source = _get_main_source()
        assert "settings.qora_allowed_origins" in source or "qora_allowed_origins" in source, (
            "main.py CORS setup must read qora_allowed_origins from a Settings instance."
        )


# ---------------------------------------------------------------------------
# Task 1.7 — Lifespan behavior: validate_all_integration_credentials is called
# ---------------------------------------------------------------------------


class TestLifespanCallsTenantValidation:
    """The lifespan function must call validate_all_integration_credentials() at startup."""

    def test_lifespan_imports_or_calls_validate_all_integration_credentials(self):
        """Source guard: validate_all_integration_credentials must be referenced in main.py.

        This is a structural pre-check. The behavioral proof is in the async
        behavior tests below. If this test fails it means the call was removed
        from source entirely, which is a clear regression signal.
        """
        source = _get_main_source()
        assert "validate_all_integration_credentials" in source, (
            "main.py lifespan must call validate_all_integration_credentials() "
            "from app.core.credentials before serving requests."
        )

    async def test_lifespan_calls_validate_tenant_credentials_during_startup(self):
        """BEHAVIOR: lifespan startup invokes validate_all_integration_credentials().

        This test enters the lifespan() context manager directly and asserts that
        mock_validate.called is True after startup completes. Source-text checks
        are NOT used here — only the actual runtime call counts.

        All heavy I/O (DB init, seed, background tasks) is patched. The goal is to
        prove the call is wired, not to test what the validator does (that is in
        test_credentials.py).

        Spec: tenant-integration-secrets — Requirement: Startup Validation for
        Configured Integrations
        """
        from fastapi import FastAPI

        from app.main import lifespan

        mini_app = FastAPI()

        with (
            patch("app.core.credentials.validate_all_integration_credentials") as mock_validate,
            patch("app.main.Settings") as mock_settings_cls,
            patch("app.main.setup_logging"),
            patch("app.core.database.init_db", new_callable=AsyncMock),
            patch("app.core.database.async_session_factory") as mock_sf,
            patch("app.core.database.close_db", new_callable=AsyncMock),
            patch("app.tenants.service.seed_quintana", new_callable=AsyncMock),
            patch("app.tenants.service.seed_qora_demo", new_callable=AsyncMock),
            patch("app.leads.service.seed_leads", new_callable=AsyncMock),
            patch("app.sweeper.stale_session_sweeper", new_callable=AsyncMock),
            patch("app.scheduler.service.scheduler_tick", new_callable=AsyncMock),
        ):
            mock_settings_cls.return_value = _make_mock_settings()
            mock_sf.return_value = _make_mock_session()

            # Enter lifespan — this runs the full startup sequence
            async with lifespan(mini_app):
                pass  # Startup completed; shutdown runs on context exit

        # The validator MUST have been called during startup, before the yield
        assert mock_validate.called, (
            "validate_all_integration_credentials() was NOT called during lifespan startup. "
            "Wire the call in main.py lifespan before the yield."
        )
        assert mock_validate.call_count == 1, (
            f"validate_all_integration_credentials() must be called exactly once during startup, "
            f"but was called {mock_validate.call_count} time(s)."
        )

    async def test_lifespan_startup_fails_when_crm_credentials_are_invalid(self):
        """NEGATIVE BEHAVIOR: lifespan must propagate SystemExit when active CRM
        credentials are missing or invalid, preventing requests from being served.

        Simulates the scenario where validate_all_integration_credentials() detects
        an active CRM integration with a missing or placeholder env var. The function
        calls sys.exit() with a descriptive message, which raises SystemExit. The
        lifespan must NOT swallow this exception — it must propagate so the process
        aborts before the yield (before any requests are served).

        Spec: tenant-integration-secrets — Requirement: Startup Validation for
        Configured Integrations
        """
        from fastapi import FastAPI

        from app.main import lifespan

        mini_app = FastAPI()

        _invalid_cred_message = (
            "Startup aborted — CRM integration credential(s) are missing or invalid:\n"
            "  • Client 'test-client': CRM integration credential env var "
            "'TEST_AIRTABLE_API_KEY' is not set."
        )

        with (
            patch("app.core.credentials.validate_all_integration_credentials") as mock_validate,
            patch("app.main.Settings") as mock_settings_cls,
            patch("app.main.setup_logging"),
            patch("app.core.database.init_db", new_callable=AsyncMock),
            patch("app.core.database.async_session_factory") as mock_sf,
            patch("app.core.database.close_db", new_callable=AsyncMock),
            patch("app.tenants.service.seed_quintana", new_callable=AsyncMock),
            patch("app.tenants.service.seed_qora_demo", new_callable=AsyncMock),
            patch("app.leads.service.seed_leads", new_callable=AsyncMock),
            patch("app.sweeper.stale_session_sweeper", new_callable=AsyncMock),
            patch("app.scheduler.service.scheduler_tick", new_callable=AsyncMock),
        ):
            mock_settings_cls.return_value = _make_mock_settings()
            mock_sf.return_value = _make_mock_session()

            # Simulate credentials.validate_all_integration_credentials() detecting
            # a missing or placeholder env var and calling sys.exit().
            mock_validate.side_effect = SystemExit(_invalid_cred_message)

            with pytest.raises(SystemExit) as exc_info:
                async with lifespan(mini_app):
                    # This line must NOT be reached — startup should abort.
                    pytest.fail(
                        "Lifespan yielded despite invalid credentials — "
                        "SystemExit must be raised before the yield."
                    )

        # Confirm the exception carries the expected credential error context
        assert "Startup aborted" in str(exc_info.value), (
            "SystemExit message must contain 'Startup aborted' for operator clarity."
        )
        # Confirm the validator was called (the failure came from it, not elsewhere)
        assert mock_validate.called, (
            "validate_all_integration_credentials() must have been called before the failure."
        )
