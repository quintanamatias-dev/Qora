"""QORA ElevenLabs Reconciler — periodic, fetch-only drift detection.

run_reconciliation_once() GETs every active, ElevenLabs-linked agent's live config
and compares it against Qora's own projection (the same payload-building helper
sync_agent_config's save path uses), reusing _compute_drift_fields for the
comparison. The result is upserted into elevenlabs_reconciliation_reports.

Never PATCHes. Report-only (design.md R-D1) — repair stays an explicit,
operator-triggered action via the existing sync path.

Spec: openspec/changes/elevenlabs-reconciler/design.md — R-D1, R-D2, Interfaces/Contracts.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.elevenlabs.models import ElevenLabsReconciliationReport
from app.elevenlabs.service import (
    _ELEVENLABS_BASE_URL,
    _compute_drift_fields,
    _custom_llm_callback_url,
    _fetch_agent_config,
    build_config_payload,
)
from app.tenants.models import Agent

logger = get_logger(__name__)

_DEFAULT_TICK_INTERVAL_HOURS = 6


def _overlay_expected_custom_llm_url(
    projection_payload: dict, agent, actual_conversation_config: dict, settings
) -> None:
    """Add the expected agent-scoped custom_llm.url to the projection in place
    when PUBLIC_BASE_URL is set and the live agent currently uses llm=custom-llm.

    Compares only the url leaf — never secrets/headers the EL dashboard may
    hold in the live custom_llm block — so drift reporting never leaks or
    flags provider-managed secrets.

    Gap closed per openspec/changes/elevenlabs-reconciler task delegation:
    reuses service.py's _custom_llm_callback_url (shared with the save path's
    _apply_custom_llm_url_override) rather than reimplementing the URL shape.
    """
    public_base_url = getattr(settings, "public_base_url", None)
    if not public_base_url:
        return

    actual_prompt = (
        actual_conversation_config.get("agent", {}).get("prompt", {})
        if isinstance(actual_conversation_config, dict)
        else {}
    )
    if actual_prompt.get("llm") != "custom-llm":
        return

    cc = projection_payload.setdefault("conversation_config", {})
    cc.setdefault("agent", {}).setdefault("prompt", {})["custom_llm"] = {
        "url": _custom_llm_callback_url(agent, public_base_url)
    }


async def run_reconciliation_once(db: AsyncSession, settings) -> None:
    """One fetch-only pass over every active, ElevenLabs-linked agent.

    Never PATCHes. A single agent's fetch/compute failure isolates to that
    agent's report row (status="error") and does not stop the pass over the
    remaining agents.

    Skips entirely (logs, no HTTP calls) when settings.elevenlabs_api_key is
    missing.
    """
    api_key_secret = getattr(settings, "elevenlabs_api_key", None)
    if not api_key_secret:
        logger.info("elevenlabs_reconciler_skipped_no_api_key")
        return

    result = await db.execute(
        select(Agent).where(
            Agent.is_active == True,  # noqa: E712
            Agent.elevenlabs_agent_id.is_not(None),
        )
    )
    agents = list(result.scalars().all())

    api_key = api_key_secret.get_secret_value()
    headers = {"xi-api-key": api_key}

    for agent in agents:
        try:
            await _reconcile_one_agent(db, agent, headers, settings)
        except Exception as exc:
            logger.warning(
                "elevenlabs_reconciler_agent_error",
                agent_id=agent.id,
                error=str(exc),
            )
            await _upsert_report(
                db,
                agent_id=agent.id,
                client_id=agent.client_id,
                status="error",
                drift_fields=None,
                status_reason=str(exc),
            )
            await db.commit()


async def _reconcile_one_agent(db: AsyncSession, agent, headers: dict, settings) -> None:
    url = f"{_ELEVENLABS_BASE_URL}/convai/agents/{agent.elevenlabs_agent_id}"

    actual = await _fetch_agent_config(
        url=url, headers=headers, elevenlabs_agent_id=agent.elevenlabs_agent_id
    )
    if actual is None:
        await _upsert_report(
            db,
            agent_id=agent.id,
            client_id=agent.client_id,
            status="error",
            drift_fields=None,
            status_reason="fetch_failed",
        )
        await db.commit()
        return

    projection_payload = build_config_payload(agent)
    actual_conversation_config = actual.get("conversation_config", {}) if isinstance(actual, dict) else {}
    _overlay_expected_custom_llm_url(projection_payload, agent, actual_conversation_config, settings)
    drift_fields = _compute_drift_fields(projection_payload, actual_conversation_config)

    if drift_fields:
        await _upsert_report(
            db,
            agent_id=agent.id,
            client_id=agent.client_id,
            status="drift",
            drift_fields=drift_fields,
            status_reason=None,
        )
    else:
        await _upsert_report(
            db,
            agent_id=agent.id,
            client_id=agent.client_id,
            status="in_sync",
            drift_fields=None,
            status_reason=None,
        )
    await db.commit()


async def _upsert_report(
    db: AsyncSession,
    *,
    agent_id: str,
    client_id: str,
    status: str,
    drift_fields: list[str] | None,
    status_reason: str | None,
) -> None:
    import json

    result = await db.execute(
        select(ElevenLabsReconciliationReport).where(
            ElevenLabsReconciliationReport.agent_id == agent_id
        )
    )
    report = result.scalar_one_or_none()

    drift_fields_json = json.dumps(drift_fields) if drift_fields is not None else None

    if report is None:
        report = ElevenLabsReconciliationReport(
            agent_id=agent_id,
            client_id=client_id,
            status=status,
            drift_fields=drift_fields_json,
            status_reason=status_reason,
            checked_at=datetime.now(timezone.utc),
        )
        db.add(report)
    else:
        report.status = status
        report.drift_fields = drift_fields_json
        report.status_reason = status_reason
        report.checked_at = datetime.now(timezone.utc)


async def reconciler_tick(settings) -> None:
    """Interval loop (elevenlabs_reconciler_interval_hours), mirrors scheduler_tick.

    Wraps each pass in try/except so an unexpected exception never kills the loop.
    Registered in main.py lifespan.
    """
    from app.core.database import get_session

    interval_hours = getattr(settings, "elevenlabs_reconciler_interval_hours", _DEFAULT_TICK_INTERVAL_HOURS)
    if interval_hours <= 0:
        logger.info("elevenlabs_reconciler_disabled", interval_hours=interval_hours)
        return

    interval_seconds = interval_hours * 3600

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            async with get_session() as db:
                await run_reconciliation_once(db, settings)
        except Exception as exc:
            logger.warning("elevenlabs_reconciler_tick_failed", error=str(exc))
