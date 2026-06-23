"""QORA Leads — Admin/debug router for lead management.

Provides endpoints for:
- GET /api/v1/leads?client_id={id} — list leads for a client
- GET /api/v1/leads/{id} — get single lead
- POST /api/v1/leads — create lead
- PATCH /api/v1/leads/{id}/status — transition status
- GET /api/v1/leads/{id}/history — call history for lead
- GET /api/v1/leads/{id}/context-preview — structured next-call context preview (Phase A)
- GET /api/v1/leads/{id}/dimension-rollups?client_id={id} — lead-level rollup counts (cubora)

Covers: T2.4 — GET/PATCH endpoints scope queries by client_id.
Security: dimension-rollups endpoint requires client_id and verifies tenant ownership.
"""

from __future__ import annotations

import json
import structlog
from collections import Counter
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_api_key
from app.leads import lead_custom_fields_service as cf_service
from app.leads.models import LeadStatus
from app.leads.service import (
    InvalidTransitionError,
    create_lead,
    get_active_profile_facts,
    get_interest_history,
    get_lead,
    list_leads_for_client,
    transition_lead_status,
)
from app.scheduler.models import ScheduledCall

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/leads",
    tags=["leads"],
    dependencies=[Depends(require_api_key)],
)


# ---------------------------------------------------------------------------
# DB dependency
# ---------------------------------------------------------------------------


async def get_db_session():
    """FastAPI dependency that yields an async DB session."""
    from app.core.database import async_session_factory

    if async_session_factory is None:
        raise RuntimeError("Database not initialized.")

    async with async_session_factory() as session:
        yield session


# ---------------------------------------------------------------------------
# Request/Response schemas
# ---------------------------------------------------------------------------


class CreateLeadRequest(BaseModel):
    """Request body for creating a new lead."""

    # Backward-compatible optional body field. New frontend calls scope by
    # `client_id` query param, matching list endpoints.
    client_id: str | None = None
    name: str
    phone: str
    notes: str | None = None
    # WU-6: optional custom fields written to lead_custom_fields table
    custom_fields: dict[str, str] | None = None

    model_config = ConfigDict(extra="forbid")


class PatchStatusRequest(BaseModel):
    """Request body for transitioning lead status."""

    status: LeadStatus


# ---------------------------------------------------------------------------
# Response helper
# ---------------------------------------------------------------------------


async def _batch_next_scheduled_call_at(
    session: AsyncSession, lead_ids: list[str]
) -> dict[str, datetime]:
    """Return {lead_id: earliest_pending_scheduled_at} for the given lead IDs.

    Issues ONE query using MIN(scheduled_at) GROUP BY lead_id, filtered to
    status IN ('pending', 'in_progress'). Uses the composite index
    ix_scheduled_calls_lead_status for efficiency.

    Returns an empty dict when lead_ids is empty (avoids unnecessary query).
    """
    if not lead_ids:
        return {}

    stmt = (
        select(
            ScheduledCall.lead_id,
            func.min(ScheduledCall.scheduled_at).label("earliest"),
        )
        .where(
            ScheduledCall.lead_id.in_(lead_ids),
            ScheduledCall.status.in_(["pending", "in_progress"]),
        )
        .group_by(ScheduledCall.lead_id)
    )
    result = await session.execute(stmt)
    return {row.lead_id: row.earliest for row in result}


def _compute_quote_fields(
    custom_fields: dict[str, str],
    crm_config: Any | None,
) -> list[dict]:
    """Compute quote-readiness fields with fill status from CRM config metadata.

    Quote-readiness source of truth is ``crm_config.quote_ready_fields`` (from
    crm.yaml), NOT the per-field ``required`` flag on ``custom_fields`` defs.
    These two can diverge: ``required`` describes write-time validation for the
    capture_data tool, while ``quote_ready_fields`` lists exactly the fields that
    must be present for a lead to be "quoted". The UI must label and count
    readiness from ``quote_ready_fields``.

    Each field dict is annotated with:
    - label, field_type, required (kept for backward compat / write validation)
    - in_quote_ready_fields (bool): field is part of the quote-readiness set
    - source ("quote_ready" | "crm_provided"): where the field belongs in the UI
    - filled (bool): whether current_value is non-null/non-empty
    - current_value: value stored in lead_custom_fields, or None

    Returns list of field dicts sorted: quote-ready unfilled first, then
    quote-ready filled, then additional CRM-provided fields.
    When crm_config is None, returns empty list (no metadata available).
    """
    if crm_config is None:
        return []

    quote_ready_keys = set(getattr(crm_config, "quote_ready_fields", None) or [])

    result: list[dict] = []
    for fd in crm_config.custom_fields:
        current_value = custom_fields.get(fd.field_key)
        filled = bool(current_value)
        in_quote_ready = fd.field_key in quote_ready_keys
        result.append({
            "field_key": fd.field_key,
            "label": fd.label,
            "field_type": fd.field_type,
            "required": fd.required,
            "in_quote_ready_fields": in_quote_ready,
            "source": "quote_ready" if in_quote_ready else "crm_provided",
            "filled": filled,
            "current_value": current_value,
        })

    # Sort: quote-ready unfilled first, then quote-ready filled, then the rest
    result.sort(key=lambda f: (not f["in_quote_ready_fields"], f["filled"]))
    return result


def _lead_to_dict(
    lead,
    *,
    next_scheduled_call_at: datetime | None = None,
    profile_facts: list | None = None,
    interest_history: list | None = None,
    custom_fields: dict[str, str] | None = None,
    crm_config: Any | None = None,
) -> dict:
    """Serialize a Lead ORM object to a response dict.

    Includes Phase 2 CRM fields (summary_last_call, interest_level, etc.),
    Phase 7 enrichment field (next_scheduled_call_at), Issue #36 additive
    fields (profile_facts, interest_history), WU-6 custom_fields dict,
    and Phase A fields: email, external_crm_id, external_lead_id, quote_fields.

    Args:
        lead: Lead ORM instance.
        next_scheduled_call_at: Optional datetime from batch enrichment query.
            Passed by list_leads(); other callers omit it (defaults to None).
        profile_facts: Pre-fetched list of active LeadProfileFact dicts (Issue #36).
            If None, defaults to empty dict in the response.
        interest_history: Pre-fetched list of LeadInterestHistory dicts (Issue #36).
            If None, defaults to empty list in the response.
        custom_fields: Pre-fetched {field_key: field_value} from lead_custom_fields (WU-6).
            If None, defaults to empty dict in the response.
        crm_config: Optional CRMConfig instance for quote_fields metadata.
            If None, quote_fields will be empty (no crm.yaml for this client).
    """
    # Group profile_facts by namespace prefix (strip trailing colon)
    grouped_profile_facts: dict = {}
    for row in profile_facts or []:
        fact_key = row.get("fact_key", "")
        # Extract namespace prefix (e.g. 'profile:married' → 'profile')
        if ":" in fact_key:
            namespace = fact_key.split(":")[0]
            value = row.get("fact_value") or fact_key[len(namespace) + 1 :]
            grouped_profile_facts.setdefault(namespace, []).append(value)

    cf = custom_fields if custom_fields is not None else {}

    return {
        "id": lead.id,
        "client_id": lead.client_id,
        "name": lead.name,
        "phone": lead.phone,
        # Phase A: email now included in detail response
        "email": getattr(lead, "email", None),
        "status": lead.status,
        "notes": lead.notes,
        "call_count": lead.call_count,
        "last_called_at": (
            lead.last_called_at.isoformat() if lead.last_called_at else None
        ),
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
        "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
        # Phase 2 CRM fields — null-safe
        "summary_last_call": lead.summary_last_call,
        "objections_heard": lead.objections_heard,
        "interest_level": lead.interest_level,
        "extracted_facts": lead.extracted_facts,
        "do_not_call": lead.do_not_call,
        "next_action": lead.next_action,
        "next_action_at": (
            lead.next_action_at.isoformat() if lead.next_action_at else None
        ),
        # Phase 7 enrichment — earliest pending/in_progress scheduled call
        "next_scheduled_call_at": (
            next_scheduled_call_at.isoformat() if next_scheduled_call_at else None
        ),
        # Issue #36 additive fields — accumulated lead profile
        "profile_facts": grouped_profile_facts,
        "interest_history": [
            {
                "interest_level": row.get("interest_level"),
                "recorded_at": row.get("recorded_at"),
            }
            for row in (interest_history or [])
        ],
        # WU-6: dynamic custom fields from lead_custom_fields table
        "custom_fields": cf,
        # Phase A: external CRM linkage — null if lead not synced
        "external_crm_id": getattr(lead, "external_crm_id", None),
        "external_lead_id": getattr(lead, "external_lead_id", None),
        # Phase A: quote fields with fill status from CRM metadata
        "quote_fields": _compute_quote_fields(cf, crm_config),
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("")
async def list_leads(
    client_id: str = Query(..., description="Tenant client ID to scope results"),
    session: AsyncSession = Depends(get_db_session),
):
    """List all leads for a given client.

    Returns each lead enriched with next_scheduled_call_at (Phase 7):
    the earliest pending/in_progress scheduled call time, or null if none.
    Uses a single batch MIN() query — no N+1.

    Returns:
        List of lead objects for the specified client_id.

    Raises:
        422: If client_id query parameter is missing.
    """
    leads = await list_leads_for_client(session, client_id.lower())
    if not leads:
        return []
    lead_ids = [lead.id for lead in leads]
    schedule_map = await _batch_next_scheduled_call_at(session, lead_ids)
    # WU-6: batch load custom fields for all leads in one query
    cf_map = await cf_service.batch_get(session, lead_ids, client_id.lower())
    return [
        _lead_to_dict(
            lead,
            next_scheduled_call_at=schedule_map.get(lead.id),
            custom_fields=cf_map.get(lead.id, {}),
        )
        for lead in leads
    ]


@router.get("/{lead_id}")
async def get_lead_by_id(
    lead_id: str,
    session: AsyncSession = Depends(get_db_session),
):
    """Get a single lead by its UUID.

    Returns:
        Lead object with all fields including accumulated profile_facts, interest_history,
        email, external CRM IDs, and annotated quote_fields (Phase A).

    Raises:
        404: If lead_id does not exist.
    """
    lead = await get_lead(session, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail={"error": "lead not found"})

    # Issue #36: Fetch accumulated profile data from relational tables
    profile_facts = await get_active_profile_facts(session, lead_id)
    interest_history = await get_interest_history(session, lead_id)
    # WU-6: load custom fields scoped to this lead's client
    custom_fields = await cf_service.get_all(session, lead_id, lead.client_id)
    # Phase 7 parity: detail endpoint must populate next_scheduled_call_at for
    # pending/in_progress scheduled calls, consistent with list_leads. Reuse the
    # same batch helper (single-element id list) so list and detail agree.
    schedule_map = await _batch_next_scheduled_call_at(session, [lead_id])

    # Phase A: load CRM config for quote_fields metadata (best-effort, None if no crm.yaml)
    crm_config = None
    try:
        from app.integrations.crm_config import CRMConfigLoader
        crm_config = CRMConfigLoader.load(lead.client_id)
    except Exception:
        logger.warning("lead_detail_crm_config_load_failed", lead_id=lead_id, client_id=lead.client_id)

    return _lead_to_dict(
        lead,
        next_scheduled_call_at=schedule_map.get(lead_id),
        profile_facts=profile_facts,
        interest_history=interest_history,
        custom_fields=custom_fields,
        crm_config=crm_config,
    )


@router.post("", status_code=201)
async def create_new_lead(
    body: CreateLeadRequest,
    client_id: str | None = Query(None, description="Tenant client ID to scope creation"),
    session: AsyncSession = Depends(get_db_session),
):
    """Create a new lead record.

    Returns:
        Created lead object (HTTP 201).
    """
    resolved_client_id = (client_id or body.client_id or "").lower()
    if not resolved_client_id:
        raise HTTPException(status_code=422, detail={"error": "client_id is required"})

    lead = await create_lead(
        session,
        client_id=resolved_client_id,
        name=body.name,
        phone=body.phone,
        notes=body.notes,
    )

    # WU-6: write custom_fields to lead_custom_fields table if provided
    if body.custom_fields:
        await cf_service.upsert_many(
            session,
            lead_id=lead.id,
            client_id=resolved_client_id,
            fields=body.custom_fields,
        )

    await session.commit()

    # Reload custom fields after commit so response reflects stored values
    custom_fields = await cf_service.get_all(session, lead.id, resolved_client_id)
    return _lead_to_dict(lead, custom_fields=custom_fields)


@router.patch("/{lead_id}/status")
async def patch_lead_status(
    lead_id: str,
    body: PatchStatusRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Transition a lead's status via the state machine.

    Returns:
        Updated lead object.

    Raises:
        404: If lead_id does not exist.
        409: If the transition is not allowed by the state machine.
        422: If status field is missing from request body.
    """
    try:
        lead = await transition_lead_status(session, lead_id, body.status)
    except ValueError:
        raise HTTPException(status_code=404, detail={"error": "lead not found"})
    except InvalidTransitionError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "invalid_transition",
                "from": e.from_status,
                "to": e.to_status,
            },
        )

    await session.commit()
    # WU-6: include custom_fields in patch status response
    custom_fields = await cf_service.get_all(session, lead_id, lead.client_id)
    return _lead_to_dict(lead, custom_fields=custom_fields)


@router.get("/{lead_id}/history")
async def get_lead_history(
    lead_id: str,
    session: AsyncSession = Depends(get_db_session),
):
    """Get call session history for a lead.

    Returns:
        Dict with lead_id and list of call sessions.

    Raises:
        404: If lead_id does not exist.
    """
    from sqlalchemy import select
    from app.calls.models import CallSession

    # Verify lead exists
    lead = await get_lead(session, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail={"error": "lead not found"})

    # Fetch all call sessions for this lead
    result = await session.execute(
        select(CallSession)
        .where(CallSession.lead_id == lead_id)
        .order_by(CallSession.started_at)
    )
    sessions = list(result.scalars().all())

    return {
        "lead_id": lead_id,
        "sessions": [
            {
                "id": cs.id,
                "client_id": cs.client_id,
                "status": cs.status,
                "outcome": cs.outcome,
                "started_at": cs.started_at.isoformat() if cs.started_at else None,
                "ended_at": cs.ended_at.isoformat() if cs.ended_at else None,
                "duration_seconds": cs.duration_seconds,
                "billable_minutes": cs.billable_minutes,
            }
            for cs in sessions
        ],
    }


# ---------------------------------------------------------------------------
# Dimension rollups endpoint (cubora-accumulated-dimension-rankings)
# ---------------------------------------------------------------------------

# Strength thresholds: count >= 3 → high, count == 2 → medium, count == 1 → low
def _issue_strength(count: int) -> str:
    """Derive service issue strength label from mention count."""
    if count >= 3:
        return "high"
    if count == 2:
        return "medium"
    return "low"


async def _build_dimension_rollups(
    session: AsyncSession,
    lead_id: str,
    client_id: str,
) -> dict:
    """Build dimension rollup counts from call_analyses for a lead scoped to a tenant.

    Queries ONLY call_analyses — does NOT read CallSession.extracted_facts.
    All queries filter by BOTH lead_id AND client_id to prevent cross-tenant
    data leakage even if lead_id is guessed by an attacker from another tenant.

    Performance strategy:
    - Scalar BI columns (primary_objection_category, primary_pain_category):
      aggregated entirely in SQL via GROUP BY + COUNT — zero Python iteration.
      These columns are indexed (ix_ca_primary_objection_category,
      ix_ca_primary_pain_category) and populated at write time.
    - JSON TEXT columns (products, specific_needs, service_issues):
      SQLite stores JSON as opaque TEXT with no native array aggregation that
      is portable across SQLite/Postgres via SQLAlchemy Core. Python parsing
      is kept but the query selects ONLY those three columns, avoiding the
      load of large TEXT blobs (summary, profile_facts, commitment_signals,
      objections, buying_signals, etc.) that are never needed here.

    Args:
        session: Async DB session.
        lead_id: Lead UUID to aggregate analyses for.
        client_id: Tenant client ID — all queries are scoped to this value to
            prevent cross-tenant exposure.

    Returns:
        Dict with detected_interests, service_issues, objections, pain_points arrays.
        All arrays sorted by count descending.
    """
    from app.calls.models import CallAnalysis
    from app.analysis.universal.interest.catalog import PRODUCT_CATALOG, NEED_TAGS

    # Authoritative allowlists for interest filtering
    product_set = set(PRODUCT_CATALOG)
    need_set = set(NEED_TAGS)

    # --- Objections (SQL GROUP BY on indexed scalar BI column) ---
    # primary_objection_category is a denormalized scalar — no Python needed.
    # Filters by BOTH lead_id AND client_id to prevent cross-tenant leakage.
    obj_stmt = (
        select(
            CallAnalysis.primary_objection_category,
            func.count().label("cnt"),
        )
        .where(
            CallAnalysis.lead_id == lead_id,
            CallAnalysis.client_id == client_id,
            CallAnalysis.primary_objection_category.isnot(None),
        )
        .group_by(CallAnalysis.primary_objection_category)
        .order_by(func.count().desc())
    )
    obj_result = await session.execute(obj_stmt)
    objections = [
        {"category": row.primary_objection_category, "count": row.cnt}
        for row in obj_result
    ]

    # --- Pain Points (SQL GROUP BY on indexed scalar BI column) ---
    # primary_pain_category is a denormalized scalar — no Python needed.
    # Filters by BOTH lead_id AND client_id to prevent cross-tenant leakage.
    pain_stmt = (
        select(
            CallAnalysis.primary_pain_category,
            func.count().label("cnt"),
        )
        .where(
            CallAnalysis.lead_id == lead_id,
            CallAnalysis.client_id == client_id,
            CallAnalysis.primary_pain_category.isnot(None),
        )
        .group_by(CallAnalysis.primary_pain_category)
        .order_by(func.count().desc())
    )
    pain_result = await session.execute(pain_stmt)
    pain_points = [
        {"category": row.primary_pain_category, "count": row.cnt}
        for row in pain_result
    ]

    # --- JSON dimensions: select only the three required TEXT columns ---
    # SQLite stores JSON as opaque TEXT; json_each() is not portable via
    # SQLAlchemy Core across SQLite/Postgres. Python parsing is kept but we
    # avoid loading all other columns (summary, profile_facts, objections, etc.)
    # by selecting only the columns we actually parse.
    # Filters by BOTH lead_id AND client_id to prevent cross-tenant leakage.
    json_stmt = (
        select(
            CallAnalysis.products,
            CallAnalysis.specific_needs,
            CallAnalysis.service_issues,
        )
        .where(
            CallAnalysis.lead_id == lead_id,
            CallAnalysis.client_id == client_id,
        )
    )
    json_result = await session.execute(json_stmt)
    rows = json_result.all()

    # --- Detected Interests ---
    # Aggregate products (PRODUCT_CATALOG) and specific_needs (NEED_TAGS)
    interest_counter: Counter = Counter()
    interest_category: dict[str, str] = {}

    # --- Service Issues ---
    issue_counter: Counter = Counter()

    for row in rows:
        # Products from PRODUCT_CATALOG
        try:
            products = json.loads(row.products or "[]")
        except (json.JSONDecodeError, TypeError):
            products = []
        for product in products:
            if isinstance(product, str) and product in product_set:
                interest_counter[product] += 1
                interest_category[product] = "product"

        # Need tags from specific_needs column
        try:
            specific_needs = json.loads(row.specific_needs or "[]")
        except (json.JSONDecodeError, TypeError):
            specific_needs = []
        for need in specific_needs:
            if isinstance(need, str) and need in need_set:
                interest_counter[need] += 1
                interest_category[need] = "need"

        # Service issues — count by category from JSON objects
        try:
            issues = json.loads(row.service_issues or "[]")
        except (json.JSONDecodeError, TypeError):
            issues = []
        for issue in issues:
            if isinstance(issue, dict) and isinstance(issue.get("category"), str):
                category = issue["category"]
                if category:
                    issue_counter[category] += 1

    detected_interests = [
        {"interest": code, "count": cnt, "category": interest_category[code]}
        for code, cnt in interest_counter.most_common()
    ]

    service_issues = [
        {"issue": cat, "count": cnt, "strength": _issue_strength(cnt)}
        for cat, cnt in issue_counter.most_common()
    ]

    return {
        "detected_interests": detected_interests,
        "service_issues": service_issues,
        "objections": objections,
        "pain_points": pain_points,
    }


@router.get("/{lead_id}/dimension-rollups")
async def get_dimension_rollups(
    lead_id: str,
    client_id: str = Query(..., description="Tenant client ID — required for tenant scoping"),
    session: AsyncSession = Depends(get_db_session),
):
    """Return lead-level dimension rollup counts from call_analyses.

    Requires client_id to prevent cross-tenant data exposure (IDOR).
    Verifies the lead belongs to the requesting tenant before returning data.
    All rollup queries filter CallAnalysis by both lead_id AND client_id.

    Queries call_analyses with aggregation per dimension — does NOT use
    CallSession.extracted_facts (which is deprecated for rollup purposes).

    Args:
        lead_id: Lead UUID to aggregate analyses for.
        client_id: Tenant client ID — mandatory, used to verify ownership and
            scope all CallAnalysis queries. Returns 404 for both unknown leads
            and leads that belong to a different tenant (oracle-safe: callers
            cannot distinguish between "does not exist" and "not yours").

    Returns:
        Dict with:
          - detected_interests: [{interest, count, category}] sorted by count desc
          - service_issues: [{issue, count, strength}] sorted by count desc
          - objections: [{category, count}] sorted by count desc
          - pain_points: [{category, count}] sorted by count desc
          All arrays are empty when no analyses exist for the lead.

    Raises:
        404: If lead_id does not exist OR if the lead belongs to a different tenant.
        422: If client_id query parameter is missing.
    """
    resolved_client_id = client_id.lower()

    lead = await get_lead(session, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail={"error": "lead not found"})

    # Tenant ownership verification — prevent IDOR cross-tenant exposure.
    # Returns 404 (same as missing lead) to avoid leaking lead existence to
    # foreign tenants — oracle-safe: callers cannot distinguish "not found"
    # from "not yours".
    if lead.client_id != resolved_client_id:
        raise HTTPException(status_code=404, detail={"error": "lead not found"})

    return await _build_dimension_rollups(session, lead_id, resolved_client_id)


# ---------------------------------------------------------------------------
# Phase A: Context preview endpoint
# ---------------------------------------------------------------------------


def _tool_names_from_definitions(tools: "list[dict] | None") -> list[str] | None:
    """Extract enabled tool names from build_voice_context() tool definitions.

    build_voice_context() returns fully-built OpenAI tool definitions
    (the same ones the agent receives). For the preview we surface only the
    operator-relevant tool names. Returns None when no tools are enabled so the
    UI can distinguish "no tools" from "empty tool list".
    """
    if not tools:
        return None
    names: list[str] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        fn = tool.get("function")
        name = None
        if isinstance(fn, dict):
            name = fn.get("name")
        if not name:
            name = tool.get("name")
        if name:
            names.append(str(name))
    return names or None


@router.get("/{lead_id}/context-preview")
async def get_lead_context_preview(
    lead_id: str,
    session: AsyncSession = Depends(get_db_session),
):
    """Return structured next-call context preview for a lead (Phase A).

    Shows the exact non-system-prompt context the agent will receive on next call.

    Source of truth: this endpoint builds the preview from the SAME runtime path
    the voice agent uses — get_default_agent() + build_voice_context(). The literal
    context blocks (lead_profile, misc_notes, skills_index, tools, model config) are
    read directly off the resulting VoiceSessionContext so the preview cannot diverge
    from what the agent actually receives. Only the system prompt is redacted — its
    presence is indicated but its content is never returned.

    call_history / is_returning_caller / call_number come from build_memory_context()
    — the same memory layer the runtime injects into the prompt at initiation.

    Returns:
        ContextPreview dict with:
          - system_prompt_present: bool (presence only — content never returned)
          - lead_profile: str (the [CONTEXTO DEL LEAD] block, or "" if none)
          - call_history: str (last 3 completed sessions with summaries, or "" if none)
          - misc_notes: str (operational notes from extracted_facts, or "" if none)
          - skills_index: str | None (Available Skills block, or None if no registry)
          - tools: list[str] | None (enabled tool names, or None)
          - model: str | None (LLM model id from runtime context, or None on error)
          - temperature: float | None (sampling temperature from runtime context)
          - max_tokens: int | None (max tokens from runtime context)
          - is_returning_caller: bool
          - call_number: int (call_count + 1 — next call index)
          - error: str | None (set when agent/context assembly failed gracefully)

    Raises:
        404: If lead_id does not exist.
    """
    lead = await get_lead(session, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail={"error": "lead not found"})

    # Memory layer — call_history, is_returning_caller, call_number. This is the
    # same builder the runtime uses at initiation, so these values match the agent.
    from app.memory import build_memory_context

    memory_ctx = await build_memory_context(session, lead)

    # Build the preview from the runtime context path so it cannot diverge from
    # what the agent receives. Defaults are returned when no agent / build fails.
    lead_profile: str = ""
    misc_notes: str = ""
    skills_index: str | None = None
    tools: list[str] | None = None
    system_prompt_present: bool = False
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    agent_error: str | None = None

    try:
        from app.tenants.service import get_client, get_default_agent
        from app.voice.context import build_voice_context

        agent = await get_default_agent(session, lead.client_id)
        client = await get_client(session, lead.client_id)

        if agent is None:
            agent_error = "No active agent found for this client — context preview unavailable"
        elif client is None:
            agent_error = "Client not found — context preview unavailable"
        else:
            # Build context via the identical runtime factory. The literal,
            # non-system-prompt fields below are read straight off the result.
            ctx = await build_voice_context(
                agent=agent,
                lead=lead,
                db=session,
                client=client,
            )

            # system prompt: presence only — content is redacted from the preview.
            system_prompt_present = bool(ctx.system_prompt and ctx.system_prompt.strip())

            # Literal non-system-prompt context — faithful to runtime assembly.
            # When the prompt template injects lead vars, the agent does NOT receive
            # a separate lead_profile block (it's substituted into the prompt). Mirror
            # that here so the preview reflects what the agent actually gets.
            lead_profile = "" if ctx.skip_lead_profile_in_assembly else (ctx.lead_profile or "")
            misc_notes = ctx.misc_notes or ""
            skills_index = ctx.skills_index
            tools = _tool_names_from_definitions(ctx.tools)

            # Model config — operator-relevant runtime config. Only real values from
            # the built context are returned; nothing is invented.
            model = ctx.model
            temperature = ctx.temperature
            max_tokens = ctx.max_tokens

    except Exception as exc:
        agent_error = f"Context assembly failed: {exc}"
        logger.warning("context_preview_assembly_failed", lead_id=lead_id, error=str(exc))

    return {
        "lead_id": lead_id,
        "system_prompt_present": system_prompt_present,
        "lead_profile": lead_profile,
        "call_history": memory_ctx["call_history"],
        "misc_notes": misc_notes,
        "skills_index": skills_index,
        "tools": tools,
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "is_returning_caller": memory_ctx["is_returning_caller"],
        "call_number": memory_ctx["call_number"],
        "error": agent_error,
    }
