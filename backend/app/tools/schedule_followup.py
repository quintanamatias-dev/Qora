"""QORA Tools — schedule_followup handler (Phase 6 upgrade).

Phase 6 changes:
- Creates a ScheduledCall record (trigger_reason='followup_tool') when scheduler_enabled
- Validates followup_date is parseable (ISO 8601 date)
- Dual-write: always appends backward-compat note to Lead.notes
- Duplicate guard: if pending ScheduledCall exists, only note is written
- Scheduler disabled: only note is written (backward-compat mode)

Covers: CAP-4 schedule_followup + REQ-TSF-001.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.leads.service import get_lead, transition_lead_status, InvalidTransitionError

logger = structlog.get_logger(__name__)


def _parse_followup_date(
    followup_date: str,
    client_timezone: str | None = None,
) -> datetime | None:
    """Parse followup_date string to a UTC-aware datetime.

    Accepts ISO 8601 date/datetime strings:
      - "2026-05-10"             → date-only: interpreted as client local midnight
      - "2026-05-10T14:00:00"   → naive datetime: interpreted as client local time
      - "2026-05-10T14:00:00-03:00" → offset-aware: used as-is, converted to UTC

    When the string is naive (no TZ info) and client_timezone is provided, the
    datetime is treated as that timezone, then converted to UTC.  If no
    client_timezone is supplied the behaviour falls back to UTC (preserves
    backward compatibility with callers that don't provide it).

    Returns:
        UTC-aware datetime, or None if unparseable.
    """
    if not followup_date or not followup_date.strip():
        return None

    stripped = followup_date.strip()

    # Normalize "Z" suffix → "+00:00" so fromisoformat() handles it on Python 3.11
    normalized = stripped.replace("Z", "+00:00") if stripped.endswith("Z") else stripped

    # Attempt to parse with fromisoformat() — accepts all valid ISO 8601 variants:
    #   date-only:            "2026-06-01"
    #   no-seconds:           "2026-06-01T14:00"
    #   with-seconds:         "2026-06-01T14:00:00"
    #   fractional-seconds:   "2026-06-01T14:00:00.123456"
    #   offset-aware:         "2026-06-01T14:00:00-03:00"
    #   UTC (Z normalized):   "2026-06-01T14:00:00Z" → "2026-06-01T14:00:00+00:00"
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if dt.tzinfo is not None:
        # Already timezone-aware → convert to UTC and return
        return dt.astimezone(timezone.utc)

    # dt is naive — localize to the client's timezone then convert to UTC
    if client_timezone:
        from zoneinfo import ZoneInfo

        local_tz = ZoneInfo(client_timezone)
        dt = dt.replace(tzinfo=local_tz).astimezone(timezone.utc)
    else:
        # No client TZ supplied → fall back to UTC (backward compat)
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


async def schedule_followup(
    session: AsyncSession,
    lead_id: str,
    followup_date: str,
    note: str | None = None,
    client_id: str | None = None,
    source_session_id: str | None = None,
) -> dict:
    """Schedule a follow-up call for a lead on a specific date.

    Phase 6 behavior:
    1. Validate followup_date is parseable (return error if not)
    2. Transition lead to follow_up state
    3. If scheduler_enabled: create ScheduledCall (with duplicate guard)
    4. Always: write backward-compat note to Lead.notes

    Args:
        session: Active async DB session.
        lead_id: UUID of the lead.
        followup_date: ISO 8601 date string (e.g., "2026-05-01").
        note: Optional — additional note for the follow-up.
        client_id: Client ID (optional — loaded from lead if not provided).
        source_session_id: Source call session (optional).

    Returns:
        Updated lead dict, or {"error": ...}.
    """
    # We need the client's timezone to correctly interpret naive datetimes.
    # Load the client early (before lead) so we can pass the TZ to the parser.
    # If client_id is not yet known, we'll re-resolve after loading the lead.
    _early_client_tz: str | None = None
    if client_id:
        try:
            from app.tenants.models import Client as _ClientModel

            _early_client = await session.get(_ClientModel, client_id)
            if _early_client is not None:
                _early_client_tz = _early_client.scheduler_timezone
        except Exception:
            pass

    # Validate followup_date is parseable (Phase 6: reject invalid AI dates)
    parsed_dt = _parse_followup_date(followup_date, client_timezone=_early_client_tz)
    if parsed_dt is None:
        logger.warning(
            "schedule_followup_invalid_date",
            lead_id=lead_id,
            followup_date=followup_date,
        )
        return {"error": "invalid_date", "field": "followup_date", "value": followup_date}

    lead = await get_lead(session, lead_id)
    if lead is None:
        return {"error": "lead_not_found"}

    # Resolve client_id from lead if not provided
    effective_client_id = client_id or lead.client_id

    # Transition to follow_up (enforces state machine)
    # Allow idempotent re-scheduling: if already in follow_up, skip the transition
    try:
        await transition_lead_status(session, lead_id, "follow_up")
    except InvalidTransitionError as e:
        if lead.status == "follow_up":
            # Already in follow_up — idempotent, continue with note+scheduler
            pass
        else:
            return {"error": f"invalid_transition: {e.from_status} → {e.to_status}"}

    # Phase 6: Attempt to create ScheduledCall (if scheduler_enabled)
    sc_created = False
    if effective_client_id:
        try:
            from app.tenants.models import Client
            from app.scheduler.service import create_scheduled_call, calculate_scheduled_at
            from app.scheduler.models import ScheduledCall
            from sqlalchemy import select

            client = await session.get(Client, effective_client_id)
            if client and client.scheduler_enabled:
                # Duplicate guard: check for existing pending/in_progress
                existing = await session.execute(
                    select(ScheduledCall).where(
                        ScheduledCall.lead_id == lead_id,
                        ScheduledCall.client_id == effective_client_id,
                        ScheduledCall.status.in_(["pending", "in_progress"]),
                    )
                )
                if existing.scalar_one_or_none() is None:
                    # Resolve agent_id: prefer source session's agent, fall back to default
                    resolved_agent_id: str | None = None
                    if source_session_id:
                        from app.calls.models import CallSession as _CallSession

                        sess_result = await session.execute(
                            select(_CallSession).where(
                                _CallSession.id == source_session_id
                            )
                        )
                        src_session = sess_result.scalar_one_or_none()
                        if src_session is not None and src_session.agent_id:
                            resolved_agent_id = src_session.agent_id

                    if resolved_agent_id is None:
                        from app.tenants.service import get_default_agent as _get_default_agent

                        default_agent = await _get_default_agent(session, effective_client_id)
                        if default_agent is not None:
                            resolved_agent_id = default_agent.id
                        else:
                            logger.warning(
                                "schedule_followup_no_default_agent",
                                client_id=effective_client_id,
                                lead_id=lead_id,
                            )

                    # Clamp to allowed hours
                    scheduled_at = calculate_scheduled_at(
                        now_utc=parsed_dt,
                        cooldown_minutes=0,  # Use the provided date directly
                        start_hour=client.scheduler_allowed_hours_start,
                        end_hour=client.scheduler_allowed_hours_end,
                        tz_str=client.scheduler_timezone,
                    )
                    await create_scheduled_call(
                        session,
                        client_id=effective_client_id,
                        lead_id=lead_id,
                        scheduled_at=scheduled_at,
                        trigger_reason="followup_tool",
                        source_session_id=source_session_id,
                        attempt_number=1,
                        max_attempts=client.scheduler_max_attempts,
                        notes=note,
                        agent_id=resolved_agent_id,
                    )
                    sc_created = True
                    logger.info(
                        "schedule_followup_scheduled_call_created",
                        lead_id=lead_id,
                        client_id=effective_client_id,
                    )
        except Exception as exc:
            logger.warning(
                "schedule_followup_scheduler_error",
                lead_id=lead_id,
                error=str(exc),
            )

    # Always: persist backward-compat note to Lead.notes
    followup_entry = f"Seguimiento agendado: {followup_date}"
    if note:
        followup_entry += f" — {note}"

    existing_notes = lead.notes or ""
    lead.notes = f"{existing_notes}\n{followup_entry}".strip() if existing_notes else followup_entry

    lead.updated_at = datetime.now(timezone.utc)
    await session.flush()

    result = {
        "id": lead.id,
        "status": lead.status,
        "followup_date": followup_date,
        "notes": lead.notes,
        "updated_at": lead.updated_at.isoformat(),
    }
    if sc_created:
        result["scheduled_call_created"] = True

    return result
