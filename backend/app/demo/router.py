"""QORA Demo — Public demo-facing API endpoints (Phase B5 PR #2).

All endpoints in this router are intentionally AUTH-EXEMPT:
  - /api/v1/demo/context                    — returns demo agent metadata (no secrets, no admin data)
  - /api/v1/demo/leads                      — returns leads scoped to the demo client only
  - /api/v1/demo/sessions/{session_id}/end  — close a demo call session (demo-scoped, no admin key)

Design rationale (design.md — Demo context + leads decision):
  - No credential reaches the browser. Server resolves identity from env vars.
  - Separate endpoints follow REST conventions and keep /demo/context lightweight.
  - Demo flow: browser GETs context → GETs leads → user starts ElevenLabs WebSocket.
    The WebSocket call triggers /voice/initiation which creates the AuthorizedSession.
  - This router is NOT for admin writes. Admin routes stay behind require_api_key.
  - /demo/sessions/{id}/end is the demo-scoped close endpoint. The admin
    /calls/{id}/end route requires require_api_key and must NOT be called
    directly from the browser (Finding 2 fix).

NEVER add require_api_key or require_webhook_secret to routes in this file.
NEVER return QORA_API_KEY, QORA_WEBHOOK_SECRET, or any admin-level data.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/demo", tags=["demo"])

_logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class DemoContextResponse(BaseModel):
    """Safe demo context — contains only data the browser needs to connect.

    Attributes:
        elevenlabs_agent_id: ElevenLabs agent ID to open the WebSocket to.
        client_name: Human-readable client/company name for display.
        agent_name: Human-readable agent name for display.
        demo_client_id: The configured demo client ID (needed by initiation webhook).
    """

    elevenlabs_agent_id: str | None
    client_name: str
    agent_name: str
    demo_client_id: str


# ---------------------------------------------------------------------------
# GET /api/v1/demo/context
# ---------------------------------------------------------------------------


@router.get("/context", response_model=DemoContextResponse)
async def get_demo_context(request: Request) -> DemoContextResponse:
    """Return demo agent metadata — auth-exempt, safe for the browser.

    Resolves the demo client and agent using QORA_DEMO_CLIENT_ID and
    QORA_DEMO_AGENT_ID environment variables. Returns only:
      - elevenlabs_agent_id (for WebSocket connection)
      - client_name (display only)
      - agent_name (display only)
      - demo_client_id (for initiation webhook routing)

    NEVER includes QORA_API_KEY, QORA_WEBHOOK_SECRET, or any admin-level data.

    Returns:
        DemoContextResponse with safe demo metadata.

    Raises:
        HTTPException(503): When QORA_DEMO_CLIENT_ID or QORA_DEMO_AGENT_ID
            are not configured (demo not set up for this environment).
        HTTPException(404): When the configured demo client or agent
            does not exist in the database.
    """
    # Read settings from app.state (populated during lifespan) or fall back
    # to a fresh Settings() for test environments that skip lifespan.
    try:
        settings = request.app.state.settings
    except AttributeError:
        from app.core.config import Settings
        settings = Settings()

    demo_client_id = settings.qora_demo_client_id
    demo_agent_id = settings.qora_demo_agent_id

    if not demo_client_id or not demo_agent_id:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "demo_not_configured",
                "message": (
                    "Demo is not configured for this environment. "
                    "Set QORA_DEMO_CLIENT_ID and QORA_DEMO_AGENT_ID in .env"
                ),
            },
        )

    # Resolve client and agent from the database.
    from app.core.database import get_session as db_session
    from app.tenants.service import get_client, get_agent

    async with db_session() as db:
        client = await get_client(db, demo_client_id)
        if client is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "demo_client_not_found",
                    "message": f"Demo client '{demo_client_id}' not found in database.",
                },
            )

        agent = await get_agent(db, demo_agent_id)
        if agent is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "demo_agent_not_found",
                    "message": f"Demo agent '{demo_agent_id}' not found in database.",
                },
            )

    return DemoContextResponse(
        elevenlabs_agent_id=agent.elevenlabs_agent_id,
        client_name=client.name,
        agent_name=agent.name,
        demo_client_id=demo_client_id,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/demo/leads
# ---------------------------------------------------------------------------


@router.get("/leads")
async def get_demo_leads(request: Request) -> list[dict]:
    """Return leads for the demo client only — auth-exempt, scoped to demo client.

    Reads QORA_DEMO_CLIENT_ID from settings and returns only leads that belong
    to that client. Cross-tenant data is impossible here: the client_id is
    derived from server-side configuration, never from user input.

    Returns:
        List of lead dicts (same shape as /api/v1/leads?client_id=...).

    Raises:
        HTTPException(503): When QORA_DEMO_CLIENT_ID is not configured.
    """
    try:
        settings = request.app.state.settings
    except AttributeError:
        from app.core.config import Settings
        settings = Settings()

    demo_client_id = settings.qora_demo_client_id
    if not demo_client_id:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "demo_not_configured",
                "message": "QORA_DEMO_CLIENT_ID is not set.",
            },
        )

    from app.core.database import get_session as db_session
    from app.leads.service import list_leads_for_client

    async with db_session() as db:
        leads = await list_leads_for_client(db, demo_client_id)

    # Return a safe subset of lead fields — no raw DB objects
    return [
        {
            "id": lead.id,
            "name": lead.name,
            "status": lead.status,
            "phone": lead.phone,
            "notes": lead.notes,
            "client_id": lead.client_id,
            # custom_fields dict (if available via property or dict attribute)
            "custom_fields": (
                lead.custom_fields
                if hasattr(lead, "custom_fields") and isinstance(lead.custom_fields, dict)
                else {}
            ),
        }
        for lead in leads
    ]


# ---------------------------------------------------------------------------
# POST /api/v1/demo/sessions/{session_id}/end
# ---------------------------------------------------------------------------


class DemoSessionEndRequest(BaseModel):
    """Request body for the demo-scoped session close endpoint."""

    reason: str = "user_hangup"
    conversation_id: str | None = None  # optional — for reconciliation
    client_id: str | None = None        # optional — for reconciliation
    lead_id: str | None = None          # optional — for reconciliation


@router.post("/sessions/{session_id}/end")
async def demo_end_call_session(session_id: str, body: DemoSessionEndRequest, request: Request):
    """Close a demo call session — auth-exempt, scoped to the demo client.

    This is the demo-scoped alternative to the admin-protected
    /api/v1/calls/{session_id}/end endpoint. The browser demo page calls this
    endpoint when the WebSocket closes so no admin API key is needed in the browser.

    Scope guard: the session must belong to the configured demo client
    (QORA_DEMO_CLIENT_ID). Sessions from other tenants are rejected with 403
    so this auth-exempt route cannot be abused to close arbitrary sessions.

    Idempotent: if the session is already closed, returns 200 without error.

    Args:
        session_id: The ElevenLabs conversation ID or internal session UUID.
        body: Optional reason and reconciliation fields.
        request: FastAPI Request (for app.state.settings access).

    Returns:
        JSON with session id, status, duration, and closed_reason.

    Raises:
        HTTPException(503): When QORA_DEMO_CLIENT_ID is not configured.
        HTTPException(404): When the session is not found.
        HTTPException(403): When the session does not belong to the demo client.
    """
    # Resolve demo_client_id from settings
    try:
        settings = request.app.state.settings
    except AttributeError:
        from app.core.config import Settings
        settings = Settings()

    demo_client_id: str | None = settings.qora_demo_client_id
    if not demo_client_id:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "demo_not_configured",
                "message": "QORA_DEMO_CLIENT_ID is not set.",
            },
        )

    from app.calls.service import close_session, get_session, get_session_by_elevenlabs_id
    from app.core.database import get_session as db_session

    async with db_session() as db:
        # Primary: resolve by ElevenLabs conversation ID (same as the admin /end route)
        cs = await get_session_by_elevenlabs_id(db, session_id)
        if cs is None:
            # Fallback: try internal session UUID
            cs = await get_session(db, session_id)

        if cs is None:
            _logger.warning(
                "demo_end_session_not_found",
                session_id=session_id,
                demo_client_id=demo_client_id,
            )
            raise HTTPException(status_code=404, detail="Call session not found")

        # Scope guard: session must belong to the configured demo client.
        # This prevents the auth-exempt endpoint from closing sessions for other tenants.
        if cs.client_id != demo_client_id:
            _logger.warning(
                "demo_end_session_client_mismatch",
                session_id=session_id,
                session_client_id=cs.client_id,
                demo_client_id=demo_client_id,
            )
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "demo_scope_violation",
                    "message": "Session does not belong to the configured demo client.",
                },
            )

        try:
            closed_session, _was_already_closed = await close_session(
                db,
                session_id=cs.id,
                closed_reason=body.reason,
                update_lead_counters=True,
                reconcile_client_id=body.client_id,
                reconcile_lead_id=body.lead_id,
            )
        except ValueError:
            raise HTTPException(status_code=404, detail="Call session not found")

    _logger.info(
        "demo_end_session_completed",
        session_id=session_id,
        resolved_id=cs.id,
        reason=body.reason,
    )

    return {
        "id": closed_session.id,
        "status": closed_session.status,
        "duration_seconds": closed_session.duration_seconds,
        "closed_reason": closed_session.closed_reason,
    }
