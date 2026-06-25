"""QORA — FastAPI application entry point.

Initializes all QORA components during lifespan startup:
1. Settings (pydantic-settings from .env)
2. Structured logging (structlog JSON)
3. Database engine + WAL pragmas (schema guaranteed by pre-start migration)
4. Seed data (Quintana Seguros client + 5 test leads)
5. Background TTL cleanup for in-memory session store

Pre-start migration:
  Schema creation and backward-compatible DDL changes are handled by Alembic
  (python scripts/migrate.py) before the app process starts. The lifespan no
  longer calls Base.metadata.create_all() or _ensure_startup_schema_compat().
  Design: phase-b-db-migration-foundation/design.md

Registers all domain routers:
- /api/v1/clients (clients full CRUD router)
- /api/v1/clients/{client_id}/agents (agents CRUD router — Phase 7)
- /api/v1/voice (initiation + custom-llm)
- /api/v1/leads (leads admin/debug router)
- /api/v1/calls (calls admin/debug router)
- /api/v1/tenants (backward-compat read-only alias)
- /api/v1/health
- /demo (voice call simulator static page)

NOTE: The admin UI is served exclusively by the React/Vite frontend at
      http://localhost:5173/admin. The previous /admin static mount has been
      removed to avoid two editable admin UIs. Do NOT re-add it here.
"""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, Request, Response

# Load ALL .env variables into os.environ so per-client credentials
# (e.g. QUINTANA_AIRTABLE_API_KEY) are available via os.environ.get().
# pydantic-settings only reads its own declared fields; this covers the rest.
# B8: Load from repo-root/.env (single source of truth).
# Path resolution: __file__ (backend/app/main.py) → .parent = backend/app/
#   → .parent = backend/ → .parent = repo-root/
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env", override=False)
from fastapi.responses import FileResponse, RedirectResponse  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint  # noqa: E402
from starlette.staticfiles import StaticFiles  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.core.logging import setup_logging, get_logger  # noqa: E402

logger = get_logger(__name__)

# Track app start time for health uptime
_APP_START_TIME: float = 0.0


# ---------------------------------------------------------------------------
# Request logging middleware
# ---------------------------------------------------------------------------


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every request with method, path, status, and latency."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start_time = time.monotonic()

        logger.info(
            "request_started",
            method=request.method,
            path=request.url.path,
        )

        try:
            response = await call_next(request)
            latency_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "request_completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                latency_ms=round(latency_ms, 2),
            )
            return response

        except Exception as exc:
            latency_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "request_error",
                method=request.method,
                path=request.url.path,
                error_type=type(exc).__name__,
                error_message=str(exc),
                latency_ms=round(latency_ms, 2),
                exc_info=True,
            )
            raise


# ---------------------------------------------------------------------------
# Session store TTL cleanup background task
# ---------------------------------------------------------------------------


async def _session_store_cleanup_task():
    """Background task to clean up expired in-memory conversation sessions.

    Runs every 60 seconds, removes sessions older than 5 minutes.
    Prevents memory leaks from abandoned conversations.
    """
    from app.voice.session import session_store

    while True:
        await asyncio.sleep(60)
        removed = session_store.cleanup_expired(ttl_seconds=300)
        if removed > 0:
            logger.info("session_store_cleanup", removed=removed)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """QORA startup/shutdown lifecycle.

    Startup:
    1. Load settings
    2. Configure logging
    3. Init database engine + WAL pragmas (schema from pre-start migration)
    4. Seed tenant + leads data
    5. Start session store TTL cleanup background task

    Shutdown:
    1. Cancel background tasks
    2. Close DB connections
    """
    global _APP_START_TIME

    # 1. Load settings
    settings = Settings()
    app.state.settings = settings

    # 2. Configure logging
    setup_logging(settings.log_level)
    logger.info(
        "qora_startup",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
    )

    # 2b. Validate per-client CRM integration credentials (B8).
    # Scans backend/clients/*/crm.yaml; hard-fails if any active integration
    # references an env var that is missing or is a weak placeholder.
    # Global Qora credentials are already validated by Settings() above.
    from app.core.credentials import validate_all_integration_credentials  # noqa: E402

    validate_all_integration_credentials()
    logger.info("tenant_credentials_validated")

    # 3. Init database
    # Schema is guaranteed by the pre-start migration command
    # (python scripts/migrate.py / alembic upgrade head).
    # init_db() only initializes the async engine, session factory, and WAL pragmas.
    from app.core import database as db_module

    await db_module.init_db(settings)
    logger.info("db_initialized", url=settings.database_url)

    # 4. Seed data
    async with db_module.async_session_factory() as session:
        from app.tenants.service import seed_quintana, seed_qora_demo
        from app.leads.service import seed_leads

        await seed_quintana(session)
        await seed_qora_demo(session)
        await seed_leads(session)
        await session.commit()

    logger.info("seed_data_loaded")
    _APP_START_TIME = time.monotonic()

    # 4b. Startup recovery for background job executor (Phase B10).
    # Re-enqueues pending/running jobs that survived a process crash.
    # Only runs when ENABLE_JOB_EXECUTOR=true — flag-off is a no-op.
    if settings.enable_job_executor:
        from app.jobs.executor import executor as job_executor

        recovered = await job_executor.recover()
        logger.info("job_executor_recovery_complete", recovered=recovered)
    else:
        logger.debug("job_executor_disabled", flag="ENABLE_JOB_EXECUTOR=false")

    # 5. Start background cleanup tasks
    cleanup_task = asyncio.create_task(_session_store_cleanup_task())

    # 6. Start stale session sweeper (CAP-2c)
    from app.sweeper import stale_session_sweeper

    sweeper_task = asyncio.create_task(stale_session_sweeper())

    # 7. Start scheduler tick (Phase 6)
    from app.scheduler.service import scheduler_tick

    scheduler_task = asyncio.create_task(scheduler_tick())
    logger.info("qora_startup_complete")

    yield

    # ---- Shutdown ----
    logger.info("qora_shutdown_started")

    # Shutdown background job executor tasks (if enabled).
    if settings.enable_job_executor:
        from app.jobs.executor import executor as job_executor
        await job_executor.shutdown()

    cleanup_task.cancel()
    sweeper_task.cancel()
    scheduler_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    try:
        await sweeper_task
    except asyncio.CancelledError:
        pass
    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass
    await db_module.close_db()
    logger.info("qora_shutdown_complete")


# ---------------------------------------------------------------------------
# API v1 router (module-level, stateless — shared across all app instances)
# ---------------------------------------------------------------------------

api_v1_router = APIRouter(prefix="/api/v1")


_APP_VERSION = "0.1.0"  # Kept in sync with create_app() FastAPI(version=...)


@api_v1_router.get("/health", tags=["meta"])
async def health_check():
    """Health check — returns service status, version, and uptime."""
    uptime = time.monotonic() - _APP_START_TIME if _APP_START_TIME > 0 else 0.0
    return {
        "status": "healthy",
        "uptime_seconds": round(uptime, 1),
        "version": _APP_VERSION,
    }


# Register domain routers
from app.tenants.router import router as tenants_router  # noqa: E402
from app.clients.router import router as clients_router  # noqa: E402
from app.agents.router import router as agents_router  # noqa: E402
from app.leads.router import router as leads_router  # noqa: E402
from app.calls.router import router as calls_router  # noqa: E402
from app.voice.initiation import router as initiation_router  # noqa: E402
from app.voice.webhook import router as webhook_router  # noqa: E402
from app.scheduler.router import router as scheduler_router  # noqa: E402
from app.analytics.router import router as analytics_router  # noqa: E402
from app.integrations.crm_router import router as crm_router  # noqa: E402
from app.integrations.crm_config_router import router as crm_config_router  # noqa: E402
from app.demo.router import router as demo_router  # noqa: E402

api_v1_router.include_router(clients_router)  # /api/v1/clients — full CRUD
api_v1_router.include_router(
    agents_router
)  # /api/v1/clients/{client_id}/agents — Phase 7
api_v1_router.include_router(tenants_router)  # /api/v1/tenants — backward-compat alias
api_v1_router.include_router(leads_router)
api_v1_router.include_router(calls_router)
api_v1_router.include_router(initiation_router)
api_v1_router.include_router(webhook_router)
api_v1_router.include_router(scheduler_router)  # /api/v1/scheduler — Phase 6
api_v1_router.include_router(analytics_router)  # /api/v1/analytics — Issue #37
api_v1_router.include_router(crm_router)  # /api/v1/clients/{client_id}/crm/import
api_v1_router.include_router(crm_config_router)  # /api/v1/clients/{client_id}/integrations
api_v1_router.include_router(demo_router)  # /api/v1/demo — public demo endpoints (Phase B5 PR #2)


# ---------------------------------------------------------------------------
# FastAPI application factory
# ---------------------------------------------------------------------------


def _parse_allowed_origins(raw: str) -> list[str]:
    """Parse QORA_ALLOWED_ORIGINS into a list of allowed origin strings.

    Args:
        raw: Comma-separated origins or "*" for wildcard (open dev default).
             Whitespace around commas is trimmed.

    Returns:
        List of origin strings. ["*"] for wildcard.

    Examples:
        "*"                                     → ["*"]
        "https://app.example.com"               → ["https://app.example.com"]
        "https://a.com, https://b.com"          → ["https://a.com", "https://b.com"]
    """
    if raw.strip() == "*":
        return ["*"]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def create_app(docs_enabled: bool | None = None) -> FastAPI:
    """Create and configure a QORA FastAPI application instance.

    Args:
        docs_enabled: When True, /docs and /redoc are mounted. When False, both
            return 404. When None (default), reads qora_docs_enabled from a
            Settings instance (the sole env authority per B8).

    Returns:
        A fully configured FastAPI instance with all middleware and API v1 routers.

    Design note:
        ``api_v1_router`` is a module-level singleton (stateless).  Multiple
        ``create_app()`` calls in the same process share the same router object;
        this is safe because routers carry no mutable per-request state.

        Module-level decorators such as ``@app.get("/admin")`` are applied only
        to the production singleton returned by ``create_app()`` at the bottom
        of this module.  Test-created apps expose the full API v1 surface but
        not the /admin redirect or the static file mounts.

        B8: docs_enabled and CORS origins are read from Settings (sole env authority)
        rather than via direct os.getenv() for these declared Settings fields.
    """
    # B8: read docs toggle and CORS origins from the Settings validator (sole env authority).
    # Settings() reads from the same env vars as the previous os.getenv() calls —
    # zero behavior change. Secret values are NEVER logged.
    #
    # Design note: Settings() is constructed here to resolve docs_enabled and CORS origins
    # via the validated Settings path. This fires at create_app() call time, which means
    # invalid configs (e.g. QORA_WEBHOOK_AUTH_ENABLED=true without a secret) surface
    # immediately — satisfying the "startup aborts before requests" spec requirement.
    _settings = Settings()

    if docs_enabled is None:
        # B8: read from settings.qora_docs_enabled — NOT via os.getenv() directly.
        docs_enabled = _settings.qora_docs_enabled

    _new_app = FastAPI(
        title="QORA",
        version="0.1.0",
        description=(
            "QORA — AI-powered outbound call center platform. "
            "ElevenLabs Conversational AI + GPT-4o + SQLite CRM."
        ),
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
    )

    # CORS lockdown (Phase B5 PR #3): use QORA_ALLOWED_ORIGINS to restrict origins.
    # Default is "*" (open) to preserve current dev behavior — set an explicit list
    # in production (e.g. "https://your-frontend.com,https://admin.your-domain.com").
    # B8: read from settings.qora_allowed_origins — routes through the Settings validator.
    _allowed_origins = _parse_allowed_origins(_settings.qora_allowed_origins)

    _new_app.add_middleware(RequestLoggingMiddleware)
    _new_app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _new_app.include_router(api_v1_router)

    return _new_app


# Module-level singleton — created once at import time using the env toggle.
# Tests that need docs-toggle behaviour should call create_app() directly.
app = create_app()

# ---------------------------------------------------------------------------
# Static files — demo page (voice call simulator)
# ---------------------------------------------------------------------------

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/demo", StaticFiles(directory=_STATIC_DIR, html=True), name="demo")

# ---------------------------------------------------------------------------
# Admin redirect — single source of truth is the React/Vite frontend
# ---------------------------------------------------------------------------
# Hitting the backend /admin URL used to 404 after the static mount was removed.
# These routes redirect both /admin and /admin/ to the canonical frontend admin
# so users following old links or bookmarks still land in the right place.


@app.get("/admin", include_in_schema=False)
@app.get("/admin/", include_in_schema=False)
async def redirect_to_frontend_admin(request: Request):
    """Redirect /admin[/] → canonical React/Vite admin UI (no trailing-slash duplicate).

    Falls back to a fresh Settings() when app.state.settings is not yet populated
    (e.g. during tests that skip the lifespan startup).
    """
    settings: Settings = getattr(request.app.state, "settings", None) or Settings()
    target = settings.frontend_url.rstrip("/") + "/admin"
    return RedirectResponse(url=target, status_code=307)


# ---------------------------------------------------------------------------
# Static frontend — Docker production build
# ---------------------------------------------------------------------------
# Serves the React SPA built by the Dockerfile Node stage.
# API routes (/api/v1/*, /demo/*, /docs, /admin) registered above take priority.
#
# Strategy: mount static assets (JS/CSS/images) via StaticFiles on /assets,
# /fonts, /images then use a FastAPI catch-all route (/{full_path:path}) to
# serve index.html for all other paths, enabling React Router deep-link support.
#
# This directory only exists inside the Docker image (/app/static-frontend/).
# Outside Docker the path is absent and all mounts/routes are skipped, leaving
# the ./Qora local dev workflow (hot-reload on :5173) completely unaffected.
# ---------------------------------------------------------------------------

_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "static-frontend")
if os.path.isdir(_FRONTEND_DIR):
    # Mount static asset directories so they are served efficiently
    for _asset_subdir in ("assets", "fonts", "images"):
        _asset_path = os.path.join(_FRONTEND_DIR, _asset_subdir)
        if os.path.isdir(_asset_path):
            app.mount(
                f"/{_asset_subdir}",
                StaticFiles(directory=_asset_path),
                name=f"frontend-{_asset_subdir}",
            )

    # Catch-all route: serve index.html for all unmatched paths so that
    # React Router can resolve deep links client-side (SPA routing support).
    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        """Serve the React SPA index.html for all unmatched GET paths."""
        return FileResponse(os.path.join(_FRONTEND_DIR, "index.html"))
