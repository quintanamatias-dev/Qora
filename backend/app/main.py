"""QORA — FastAPI application entry point.

Initializes all QORA components during lifespan startup:
1. Settings (pydantic-settings from .env)
2. Structured logging (structlog JSON)
3. Database engine + tables (SQLAlchemy async)
4. Seed data (Quintana Seguros client + 5 test leads)
5. Background TTL cleanup for in-memory session store

Registers all domain routers:
- /api/v1/clients (clients full CRUD router)
- /api/v1/clients/{client_id}/agents (agents CRUD router — Phase 7)
- /api/v1/voice (initiation + custom-llm)
- /api/v1/leads (leads admin/debug router)
- /api/v1/calls (calls admin/debug router)
- /api/v1/tenants (backward-compat read-only alias)
- /api/v1/health
- /admin (internal admin UI — Phase 7)
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.staticfiles import StaticFiles

from app.core.config import Settings
from app.core.logging import setup_logging, get_logger

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
    from app.voice.filler import session_store

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
    3. Init database + create tables
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

    # 3. Init database
    from app.core import database as db_module

    await db_module.init_db(settings)
    logger.info("db_initialized", url=settings.database_url)

    # 4. Seed data
    async with db_module.async_session_factory() as session:
        from app.tenants.service import seed_quintana, seed_demo_inmobiliaria
        from app.leads.service import seed_leads, seed_inmobiliaria_leads

        await seed_quintana(session)
        await seed_demo_inmobiliaria(session)
        await seed_leads(session)
        await seed_inmobiliaria_leads(session)
        await session.commit()

    logger.info("seed_data_loaded")
    _APP_START_TIME = time.monotonic()

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
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="QORA",
    version="0.1.0",
    description=(
        "QORA — AI-powered outbound call center platform. "
        "ElevenLabs Conversational AI + GPT-4o + SQLite CRM."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# API v1 router
# ---------------------------------------------------------------------------

api_v1_router = APIRouter(prefix="/api/v1")


@api_v1_router.get("/health", tags=["meta"])
async def health_check():
    """Health check — returns service status and uptime."""
    uptime = time.monotonic() - _APP_START_TIME if _APP_START_TIME > 0 else 0.0
    return {
        "status": "healthy",
        "uptime_seconds": round(uptime, 1),
        "version": app.version,
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

app.include_router(api_v1_router)

# ---------------------------------------------------------------------------
# Static files — demo page (voice call simulator)
# ---------------------------------------------------------------------------

import os  # noqa: E402

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/demo", StaticFiles(directory=_STATIC_DIR, html=True), name="demo")
