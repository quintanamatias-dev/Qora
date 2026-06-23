"""QORA Voice — Conversation initiation webhook.

ElevenLabs calls this endpoint before the agent speaks to get lead context.
The system responds with dynamic_variables that get injected into the agent's
system prompt via template variables.

Covers: CAP-2 pre-call lead injection, CAP-6 memory injection.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.core.auth import create_authorized_session, require_webhook_secret
from app.core.database import get_session as db_session
from app.leads.service import get_lead, transition_lead_status
from app.leads.service import InvalidTransitionError
from app.memory import build_memory_context
from app.tenants.service import get_client, get_default_agent
from app.voice.context import build_voice_context
from app.voice.session import session_store

logger = structlog.get_logger()

router = APIRouter(prefix="/voice", tags=["voice"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class InitiationRequest(BaseModel):
    """ElevenLabs initiation webhook payload.

    All fields optional so the endpoint can accept an empty body ({}) from
    ElevenLabs when client_id/lead_id are passed via query params instead.
    The handler resolves client_id from query params → body, raising 422
    only when missing from BOTH sources.
    """

    client_id: str | None = None
    lead_id: str | None = None
    agent_id: str | None = None
    called_number: str | None = None
    conversation_id: str | None = None  # VSC-5: used to pre-build and cache context


class InitiationResponse(BaseModel):
    """Response expected by ElevenLabs with dynamic variables."""

    type: str = "conversation_initiation_client_data"
    dynamic_variables: dict[str, str | int | bool]


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/initiation", response_model=InitiationResponse)
async def initiation_webhook(
    request: Request,
    body: InitiationRequest | None = None,
    client_id: str | None = Query(default=None),
    lead_id: str | None = Query(default=None),
    _webhook_auth: None = Depends(require_webhook_secret),
) -> InitiationResponse:
    """Handle ElevenLabs conversation initiation.

    Supports two ways to pass client_id and lead_id:
    1. JSON body (for Custom LLM webhook mode)
    2. Query params ?client_id=...&lead_id=... (for widget mode)
    """
    # Resolve from query params first, fall back to body.
    # Guard against FastAPI Query sentinel objects leaking in direct (test) calls.
    _client_id_qp = client_id if isinstance(client_id, str) else None
    _lead_id_qp = lead_id if isinstance(lead_id, str) else None

    # Also support tests that pass InitiationRequest as positional `request` arg
    _body_fallback = request if isinstance(request, InitiationRequest) else body

    resolved_client_id = _client_id_qp or (
        _body_fallback.client_id if _body_fallback else None
    )
    resolved_lead_id = _lead_id_qp or (
        _body_fallback.lead_id if _body_fallback else None
    )
    resolved_conversation_id = (
        _body_fallback.conversation_id if _body_fallback else None
    )

    if not resolved_client_id:
        raise HTTPException(status_code=422, detail="client_id is required")

    async with db_session() as session:
        # Load tenant config (if client not found, raise 404)
        client = await get_client(session, resolved_client_id)
        if client is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "client not found"},
            )

        # Phase 7: resolve default Agent to get agent_name (and other config)
        agent = await get_default_agent(session, resolved_client_id)

        # Default empty variables (CAP-2: unknown lead still gets empty strings)
        lead_name = ""
        car_make = ""
        car_model = ""
        car_year = ""
        current_insurance = ""
        lead_status = ""
        lead_notes = ""

        # CAP-6 memory defaults — safe fallbacks when no lead or no history
        call_history: str = ""
        confirmed_facts: str = ""
        is_returning_caller: bool = False
        call_number: int = 1

        # Load lead if lead_id was provided
        if resolved_lead_id:
            lead = await get_lead(session, resolved_lead_id)

            if lead is not None and lead.client_id != resolved_client_id:
                logger.warning(
                    "initiation_lead_client_mismatch",
                    lead_id=lead.id,
                    client_id=resolved_client_id,
                )
                lead = None

            if lead is not None:
                # CAP-6: Block initiation for do_not_call leads BEFORE any call is made
                if lead.do_not_call:
                    logger.info(
                        "initiation_blocked_do_not_call",
                        lead_id=lead.id,
                        client_id=resolved_client_id,
                    )
                    raise HTTPException(
                        status_code=403,
                        detail="Lead has opted out of calls",
                    )

                lead_name = lead.name
                # dynamic-lead-fields WU-7: read car/insurance data from lead_custom_fields
                # (AC-1: legacy ORM columns no longer read in active production paths).
                try:
                    from app.leads.lead_custom_fields_service import get_all as _get_cf_all

                    _lcf = await _get_cf_all(session, lead.id, resolved_client_id)
                except Exception:
                    _lcf = {}

                car_make = _lcf.get("car_make", "")
                car_model = _lcf.get("car_model", "")
                _cy_raw = _lcf.get("car_year", "")
                car_year = str(_cy_raw) if _cy_raw else ""
                current_insurance = _lcf.get("current_insurance", "")
                lead_status = lead.status
                lead_notes = lead.notes or ""

                # CAP-4: Delegate to shared memory builder (qora-memory-in-prompt)
                # Replaces inline _format_call_history / _format_confirmed_facts
                memory = await build_memory_context(session, lead)
                call_history = memory["call_history"]
                confirmed_facts = memory["confirmed_facts"]
                is_returning_caller = memory["is_returning_caller"]
                call_number = memory["call_number"]

                # Lead lifecycle: create_session already transitions new→called
                # and close_session increments call_count + last_called_at.
                # Initiation transition kept as idempotent safety net only.
                try:
                    await transition_lead_status(session, lead.id, "called")
                except InvalidTransitionError:
                    # Already in a state where 'called' isn't valid (e.g., interested)
                    pass

        # Phase 7: use agent.name when available, else fall back to client.agent_name
        resolved_agent_name = agent.name if agent is not None else client.agent_name

        # VSC-5: Build and cache voice context when conversation_id is provided.
        # Done inside the DB session block so build_voice_context can query memory.
        # On failure: log and continue — context=None triggers lazy fallback in webhook.
        _vsc_context = None
        if resolved_conversation_id and agent is not None:
            try:
                _lead_for_context = lead if resolved_lead_id and "lead" in dir() else None
                # 'lead' is only defined if resolved_lead_id was set
                _lead_for_context = locals().get("lead")
                _vsc_context = await build_voice_context(
                    agent=agent,
                    lead=_lead_for_context,
                    db=session,
                    client=client,
                )
            except Exception as exc:
                logger.warning(
                    "voice_context_build_failed",
                    client_id=resolved_client_id,
                    conversation_id=resolved_conversation_id,
                    error_type=type(exc).__name__,
                    error_msg=str(exc),
                )

        # VSC-5: Store session state with context (context=None if build failed or no conv_id)
        # Phase B5 PR #2: Bind AuthorizedSession at session start — production flow.
        # The session is NOT a demo session here (demo has its own initiation path via
        # the demo router). This path handles all ElevenLabs-initiated webhook calls.
        if resolved_conversation_id:
            _agent_id_for_auth = agent.id if agent is not None else None
            _agent_slug_for_auth = getattr(agent, "slug", None) if agent is not None else None
            _auth_session = create_authorized_session(
                client_id=resolved_client_id,
                agent_id=_agent_id_for_auth,
                lead_id=resolved_lead_id,
                session_id="",  # No call_session yet at initiation time
                is_demo=False,
                agent_slug=_agent_slug_for_auth,
            )
            session_store.create(
                conversation_id=resolved_conversation_id,
                client_id=resolved_client_id,
                lead_id=resolved_lead_id,
                session_id="",  # No call_session for initiation-only store
                context=_vsc_context,
                auth=_auth_session,
            )

        return InitiationResponse(
            dynamic_variables={
                # Plain names — kept for backward-compat and existing tests
                "lead_name": lead_name,
                "car_make": car_make,
                "car_model": car_model,
                "car_year": car_year,
                "current_insurance": current_insurance,
                "lead_status": lead_status,
                "lead_notes": lead_notes,
                "company_name": client.name,
                # DEPRECATED: use company_name instead.
                "broker_name": client.name,
                "agent_name": resolved_agent_name,
                # Underscore-wrapped names required by the ElevenLabs agent template.
                # The agent's first message is: ¡Hola! ¿Hablo con {{_lead_name_}}?
                "_lead_name_": lead_name,
                "_car_make_": car_make,
                "_car_model_": car_model,
                "_car_year_": car_year,
                "_current_insurance_": current_insurance,
                "_company_name_": client.name,
                # DEPRECATED: use _company_name_ instead.
                "_broker_name_": client.name,
                "_agent_name_": resolved_agent_name,
                # CAP-6: Memory injection variables
                "call_history": call_history,
                "confirmed_facts": confirmed_facts,
                "is_returning_caller": is_returning_caller,
                "call_number": call_number,
                # Underscore-wrapped variants for ElevenLabs template syntax
                "_call_history_": call_history,
                "_confirmed_facts_": confirmed_facts,
                "_is_returning_caller_": is_returning_caller,
                "_call_number_": call_number,
            }
        )
