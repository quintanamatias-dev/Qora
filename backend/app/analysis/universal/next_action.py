"""Next action — Post-Analysis Decision Engine (qora-next-action, Issue #47).

Replaces the old naive parallel GPT dimension with a priority-ordered
rules engine + GPT fallback pipeline that runs AFTER all other dimensions
complete. Receives structured dimension outputs via NextActionContext and
returns a NextActionResult that drives both lead status and the scheduler.

Decision flow (strict priority order, first match wins):
    P1 — Hard stops (close_lead): bad outcome classification, do_not_call flag,
         unresolved hard rejection + client flag
    P2 — Max attempts (close_lead): call_count >= client.next_action_max_attempts
    P3 — Commitment-based (schedule_call / follow_up): callback → schedule_call,
         receive_quote → follow_up, consult_third_party → follow_up
    P4 — No useful conversation (retry_call): no_answer / busy / technical_issue,
         abrupt + external_interruption
    P5 — Interest + outcome signal (follow_up / close_lead): threshold rules
    P6 — GPT fallback (all actions): invoked only when no rule matches
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Callable, Literal
from zoneinfo import ZoneInfo

from openai import AsyncOpenAI
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output schema (Pydantic — serialized to facts dict)
# ---------------------------------------------------------------------------


class NextActionResult(BaseModel):
    """Output of the next_action decision engine.

    Serialized via model_dump() and stored in facts["next_action_result"].
    """

    action: Literal[
        "follow_up", "retry_call", "schedule_call", "close_lead", "human_review"
    ]
    reason: str
    confidence: Literal["high", "medium", "low"]
    decided_by: Literal["rules", "gpt"]
    next_action_at: datetime | None = None
    priority: Literal["urgent", "normal", "low"] = "normal"


# ---------------------------------------------------------------------------
# Internal context (dataclasses — NOT Pydantic, never serialized externally)
# ---------------------------------------------------------------------------


@dataclass
class LeadSnapshot:
    """Snapshot of lead state at analysis time."""

    call_count: int
    do_not_call: bool
    last_called_at: datetime | None


@dataclass
class ClientRules:
    """Client-configurable thresholds for the next_action engine."""

    max_attempts: int
    min_interest_for_followup: int
    close_on_hard_rejection: bool
    scheduler_cooldown_minutes: int
    scheduler_allowed_hours_start: int
    scheduler_allowed_hours_end: int
    scheduler_timezone: str


@dataclass
class NextActionContext:
    """All structured outputs + lead state + client rules assembled for the engine.

    Built from asyncio.gather results AFTER all dimensions complete.
    Never contains the raw transcript.
    """

    from app.analysis.universal.outcome import CallOutcome
    from app.analysis.universal.commitments import CommitmentsAxis
    from app.analysis.universal.objections import ObjectionsAxis
    from app.analysis.universal.problem import ProblemAxis

    outcome: "CallOutcome"
    interest_level: int
    commitments: "CommitmentsAxis"
    objections: "ObjectionsAxis"
    problem: "ProblemAxis"
    lead: LeadSnapshot
    client: ClientRules
    # C6: telephony_status at session-end — used by voicemail recontact rule (P3.5).
    # None when context is built without telephony state (e.g. GPT-only path).
    telephony_status: "str | None" = None


# ---------------------------------------------------------------------------
# Timing helper
# ---------------------------------------------------------------------------


def _calculate_retry_scheduled_at(
    now_utc: datetime,
    cooldown_minutes: int,
    start_hour: int,
    end_hour: int,
    tz_str: str,
) -> datetime:
    """Calculate next retry time respecting allowed hours in client timezone.

    Mirrors the logic of scheduler.service.calculate_scheduled_at — duplicated
    here to preserve the app.analysis.* architectural boundary (no scheduler imports).

    Algorithm:
    1. candidate = now_utc + cooldown_minutes
    2. Convert candidate to client TZ
    3. If local hour in [start_hour, end_hour) → return as UTC (no clamp)
    4. If local hour < start_hour → clamp to start_hour same day
    5. If local hour >= end_hour → clamp to start_hour next day
    """
    tz = ZoneInfo(tz_str)
    candidate_utc = now_utc + timedelta(minutes=cooldown_minutes)
    local = candidate_utc.astimezone(tz)

    if start_hour <= local.hour < end_hour:
        return candidate_utc

    if local.hour < start_hour:
        clamped_local = datetime.combine(
            local.date(), time(start_hour, 0, 0), tzinfo=tz
        )
    else:
        next_date = local.date() + timedelta(days=1)
        clamped_local = datetime.combine(next_date, time(start_hour, 0, 0), tzinfo=tz)

    return clamped_local.astimezone(timezone.utc)


def _due_to_utc(
    due: str,
    tz_str: str,
    start_hour: int,
    now_utc: datetime,
) -> datetime | None:
    """Map a commitment 'due' string to a UTC datetime.

    Args:
        due: One of: today, tomorrow, this_week, specific_date, unknown
        tz_str: IANA timezone string for the client.
        start_hour: Client's scheduler_allowed_hours_start.
        now_utc: Current UTC datetime (for relative calculations).

    Returns:
        UTC-aware datetime, or None if due is 'specific_date' or 'unknown'
        (caller falls back to calculate_scheduled_at).
    """
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(tz_str)
    now_local = now_utc.astimezone(tz)

    if due == "today":
        target_date = now_local.date()
        clamped_local = datetime.combine(target_date, time(start_hour, 0, 0), tzinfo=tz)
        # If already past start_hour today, use it anyway (scheduler will deal with it)
        return clamped_local.astimezone(timezone.utc)

    if due == "tomorrow":
        target_date = now_local.date() + timedelta(days=1)
        clamped_local = datetime.combine(target_date, time(start_hour, 0, 0), tzinfo=tz)
        return clamped_local.astimezone(timezone.utc)

    if due == "this_week":
        target_date = now_local.date() + timedelta(days=2)
        clamped_local = datetime.combine(target_date, time(start_hour, 0, 0), tzinfo=tz)
        return clamped_local.astimezone(timezone.utc)

    # specific_date or unknown: caller falls back to calculate_scheduled_at
    return None


# ---------------------------------------------------------------------------
# Rule functions — each returns NextActionResult | None (None = no match)
# ---------------------------------------------------------------------------

# Hard stop outcome classifications (P1)
_HARD_STOP_CLASSIFICATIONS = {"do_not_contact", "wrong_number", "hostile"}

# Retry-worthy outcome classifications (P4)
_RETRY_CLASSIFICATIONS = {"no_answer", "busy", "technical_issue"}

# Follow-up-eligible outcome classifications (P5)
_FOLLOW_UP_CLASSIFICATIONS = {"completed_positive", "completed_neutral"}


def _rule_hard_stops(ctx: NextActionContext) -> NextActionResult | None:
    """P1 — Hard stop rules (close_lead).

    Fires for:
    - outcome.classification in {do_not_contact, wrong_number, hostile}
    - lead.do_not_call == True
    - Hard rejection objection + client.close_on_hard_rejection == True
    """
    # Bad outcome classification
    if ctx.outcome.classification in _HARD_STOP_CLASSIFICATIONS:
        return NextActionResult(
            action="close_lead",
            reason=f"Hard stop: outcome classification is '{ctx.outcome.classification}'",
            confidence="high",
            decided_by="rules",
        )

    # Existing do_not_call flag
    if ctx.lead.do_not_call:
        return NextActionResult(
            action="close_lead",
            reason="Lead has do_not_call flag set from a previous interaction",
            confidence="high",
            decided_by="rules",
        )

    # Hard rejection objection with client flag enabled
    if ctx.client.close_on_hard_rejection:
        for objection in ctx.objections.objections or []:
            if (
                objection.category == "hard_rejection"
                and objection.strength == "high"
                and objection.resolution_status == "unresolved"
            ):
                return NextActionResult(
                    action="close_lead",
                    reason="Unresolved hard rejection objection detected; client configured to close on hard rejection",
                    confidence="high",
                    decided_by="rules",
                )

    return None


def _rule_max_attempts(ctx: NextActionContext) -> NextActionResult | None:
    """P2 — Max attempts exhausted (close_lead)."""
    if ctx.lead.call_count >= ctx.client.max_attempts:
        return NextActionResult(
            action="close_lead",
            reason=f"Max attempts reached: {ctx.lead.call_count} >= {ctx.client.max_attempts}",
            confidence="high",
            decided_by="rules",
        )
    return None


def _rule_commitment_based(ctx: NextActionContext) -> NextActionResult | None:
    """P3 — Commitment-based rules (schedule_call / follow_up).

    Evaluates:
    - callback commitment (strong/medium, owner=lead/both) → schedule_call
    - receive_quote commitment (strong/medium) → follow_up
    - consult_third_party commitment → follow_up
    """
    now_utc = datetime.now(timezone.utc)

    for commitment in ctx.commitments.commitments or []:
        if commitment.type == "callback":
            # Only strong/medium strength and lead/both owner
            if commitment.strength in ("strong", "medium") and commitment.owner in (
                "lead",
                "both",
            ):
                # Derive next_action_at from commitment due
                next_at = _due_to_utc(
                    commitment.due,
                    ctx.client.scheduler_timezone,
                    ctx.client.scheduler_allowed_hours_start,
                    now_utc,
                )
                # Fallback to scheduler cooldown if _due_to_utc returns None
                if next_at is None:
                    next_at = _calculate_retry_scheduled_at(
                        now_utc=now_utc,
                        cooldown_minutes=ctx.client.scheduler_cooldown_minutes,
                        start_hour=ctx.client.scheduler_allowed_hours_start,
                        end_hour=ctx.client.scheduler_allowed_hours_end,
                        tz_str=ctx.client.scheduler_timezone,
                    )
                return NextActionResult(
                    action="schedule_call",
                    reason=f"Callback commitment (strength={commitment.strength}, owner={commitment.owner}, due={commitment.due})",
                    confidence="high",
                    decided_by="rules",
                    next_action_at=next_at,
                )

        elif commitment.type == "receive_quote" and commitment.strength in (
            "strong",
            "medium",
        ):
            return NextActionResult(
                action="follow_up",
                reason=f"Lead committed to receiving a quote (strength={commitment.strength})",
                confidence="high",
                decided_by="rules",
            )

        elif commitment.type == "consult_third_party":
            return NextActionResult(
                action="follow_up",
                reason="Lead needs to consult a third party before deciding",
                confidence="medium",
                decided_by="rules",
            )

    return None


def _rule_no_useful_conversation(ctx: NextActionContext) -> NextActionResult | None:
    """P4 — No useful conversation occurred (retry_call).

    Fires for:
    - outcome.classification in {no_answer, busy, technical_issue}
    - outcome.was_abrupt=True + abandonment_trigger in {external_interruption, time_constraint}
    """
    now_utc = datetime.now(timezone.utc)

    if ctx.outcome.classification in _RETRY_CLASSIFICATIONS:
        next_at = _calculate_retry_scheduled_at(
            now_utc=now_utc,
            cooldown_minutes=ctx.client.scheduler_cooldown_minutes,
            start_hour=ctx.client.scheduler_allowed_hours_start,
            end_hour=ctx.client.scheduler_allowed_hours_end,
            tz_str=ctx.client.scheduler_timezone,
        )
        return NextActionResult(
            action="retry_call",
            reason=f"No useful conversation: outcome is '{ctx.outcome.classification}'",
            confidence="high",
            decided_by="rules",
            next_action_at=next_at,
        )

    # Abrupt call ending due to external interruption or time constraint
    if ctx.outcome.was_abrupt and ctx.outcome.abandonment_trigger in (
        "external_interruption",
        "time_constraint",
    ):
        next_at = _calculate_retry_scheduled_at(
            now_utc=now_utc,
            cooldown_minutes=ctx.client.scheduler_cooldown_minutes,
            start_hour=ctx.client.scheduler_allowed_hours_start,
            end_hour=ctx.client.scheduler_allowed_hours_end,
            tz_str=ctx.client.scheduler_timezone,
        )
        return NextActionResult(
            action="retry_call",
            reason=f"Call ended abruptly due to {ctx.outcome.abandonment_trigger}",
            confidence="medium",
            decided_by="rules",
            next_action_at=next_at,
        )

    return None


def _rule_interest_outcome(ctx: NextActionContext) -> NextActionResult | None:
    """P5 — Interest + outcome signal rules (follow_up / close_lead).

    Fires for:
    - interest_level >= min_interest AND outcome in {completed_positive, completed_neutral} → follow_up
    - interest_level < 20 AND outcome == completed_negative → close_lead
    """
    if (
        ctx.interest_level >= ctx.client.min_interest_for_followup
        and ctx.outcome.classification in _FOLLOW_UP_CLASSIFICATIONS
    ):
        return NextActionResult(
            action="follow_up",
            reason=f"Interest level {ctx.interest_level} meets threshold and outcome is {ctx.outcome.classification}",
            confidence="medium",
            decided_by="rules",
        )

    if ctx.interest_level < 20 and ctx.outcome.classification == "completed_negative":
        return NextActionResult(
            action="close_lead",
            reason=f"Very low interest ({ctx.interest_level}) with completed_negative outcome",
            confidence="medium",
            decided_by="rules",
        )

    return None


def _rule_voicemail_recontact(ctx: NextActionContext) -> NextActionResult | None:
    """P3.5 — Voicemail session → schedule recontact via client policy.

    C6: When telephony_status == 'voicemail', the call hit voicemail and was
    terminated. Schedule a recontact using the client's cooldown/hours config.
    This rule fires AFTER P3 (commitments) and BEFORE P4 (no-useful-conversation)
    to keep voicemail as a business outcome (not a no-useful-conversation signal).

    Does NOT increment recontact counter here — auto_schedule() handles counting.
    """
    if ctx.telephony_status != "voicemail":
        return None

    now_utc = datetime.now(timezone.utc)
    next_at = _calculate_retry_scheduled_at(
        now_utc=now_utc,
        cooldown_minutes=ctx.client.scheduler_cooldown_minutes,
        start_hour=ctx.client.scheduler_allowed_hours_start,
        end_hour=ctx.client.scheduler_allowed_hours_end,
        tz_str=ctx.client.scheduler_timezone,
    )
    return NextActionResult(
        action="retry_call",
        reason="Voicemail detected: scheduled recontact via client policy",
        confidence="high",
        decided_by="rules",
        next_action_at=next_at,
    )


# ---------------------------------------------------------------------------
# Rules list — evaluation order defines priority
# ---------------------------------------------------------------------------

_RULES: list[Callable[[NextActionContext], NextActionResult | None]] = [
    _rule_hard_stops,  # P1
    _rule_max_attempts,  # P2
    _rule_commitment_based,  # P3
    _rule_voicemail_recontact,  # P3.5 — C6: voicemail recontact
    _rule_no_useful_conversation,  # P4
    _rule_interest_outcome,  # P5
]


def _evaluate_rules(ctx: NextActionContext) -> NextActionResult | None:
    """Evaluate rules in priority order. Returns first non-None result."""
    for rule in _RULES:
        result = rule(ctx)
        if result is not None:
            return result
    return None


# ---------------------------------------------------------------------------
# GPT fallback (P6) — invoked only when no rule matched
# ---------------------------------------------------------------------------

_GPT_SYSTEM_PROMPT = """You are a sales call analysis engine. Given a structured JSON context of a call analysis, \
determine the best next action for this lead.

You MUST return ONLY valid JSON with exactly these fields:
{
  "action": "<one of: follow_up, retry_call, schedule_call, close_lead, human_review>",
  "reason": "<one sentence explanation>",
  "confidence": "<one of: high, medium, low>"
}

Valid actions:
- follow_up: Lead shows interest, send follow-up (email, message, etc.)
- retry_call: Call again (previous call was inconclusive)
- schedule_call: Schedule a specific call (with a committed time)
- close_lead: No further action needed (lead is uninterested or unreachable)
- human_review: Situation is unclear — escalate to a human

ONLY use human_review for genuinely ambiguous cases where you cannot determine the right action.
Return ONLY the JSON object, no other text."""

_GPT_VALIDATION_PROMPT = """You are a sales call analysis engine acting as a second opinion.

A rules engine already analyzed this call and proposed an action. Your job is to INDEPENDENTLY \
evaluate the same context and decide whether you AGREE or DISAGREE with the proposed action.

You MUST return ONLY valid JSON with exactly these fields:
{
  "agrees": true or false,
  "action": "<your independent recommendation — one of: follow_up, retry_call, schedule_call, close_lead, human_review>",
  "reason": "<one sentence explaining your independent assessment>",
  "confidence": "<one of: high, medium, low>"
}

Think independently. Do NOT blindly agree with the proposed action — evaluate the full context \
on its own merits and give your honest assessment. If the proposed action is correct, agree. \
If you see a better action given the context, disagree and state your recommendation.

Return ONLY the JSON object, no other text."""


def _build_context_dict(ctx: NextActionContext) -> dict:
    """Serialize NextActionContext to a plain dict for GPT consumption."""
    return {
        "outcome": {
            "classification": ctx.outcome.classification,
            "reason": ctx.outcome.reason,
            "confidence": ctx.outcome.confidence,
            "was_abrupt": ctx.outcome.was_abrupt,
            "abandonment_trigger": ctx.outcome.abandonment_trigger,
        },
        "interest_level": ctx.interest_level,
        "commitments": [
            {
                "type": c.type,
                "owner": c.owner,
                "strength": c.strength,
                "due": c.due,
            }
            for c in (ctx.commitments.commitments or [])
        ],
        "objections": [
            {
                "category": o.category,
                "strength": o.strength,
                "resolution_status": o.resolution_status,
            }
            for o in (ctx.objections.objections or [])
        ],
        "lead": {
            "call_count": ctx.lead.call_count,
            "do_not_call": ctx.lead.do_not_call,
        },
        "client_rules": {
            "max_attempts": ctx.client.max_attempts,
            "min_interest_for_followup": ctx.client.min_interest_for_followup,
            "close_on_hard_rejection": ctx.client.close_on_hard_rejection,
        },
    }


async def _gpt_fallback(
    ctx: NextActionContext, openai_client: AsyncOpenAI
) -> NextActionResult:
    """P6 — GPT fallback for ambiguous cases.

    Sends NextActionContext as structured JSON (NOT the transcript).
    Constrained to return exactly one of the 5 valid actions.

    Args:
        ctx: NextActionContext with all dimension outputs and lead/client data.
        openai_client: AsyncOpenAI client for GPT call.

    Returns:
        NextActionResult with decided_by="gpt".
    """
    ctx_dict = _build_context_dict(ctx)
    payload = json.dumps(ctx_dict, default=str)

    response = await openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": _GPT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Analyze this call context and determine next action:\n{payload}",
            },
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )

    raw_content = response.choices[0].message.content or "{}"

    try:
        parsed = json.loads(raw_content)
    except json.JSONDecodeError:
        logger.error("next_action_gpt_fallback_json_error", raw=raw_content[:200])
        return NextActionResult(
            action="human_review",
            reason="GPT response could not be parsed as JSON",
            confidence="low",
            decided_by="gpt",
        )

    action = parsed.get("action", "human_review")
    reason = parsed.get("reason", "GPT determination")
    confidence = parsed.get("confidence", "low")

    # Validate action vocabulary — reject invalid values
    valid_actions = {
        "follow_up",
        "retry_call",
        "schedule_call",
        "close_lead",
        "human_review",
    }
    if action not in valid_actions:
        logger.warning(
            "next_action_gpt_invalid_action",
            invalid_action=action,
            valid_actions=list(valid_actions),
        )
        action = "human_review"
        reason = f"GPT returned invalid action '{action}'; escalated to human_review"
        confidence = "low"

    # Validate confidence vocabulary
    valid_confidence = {"high", "medium", "low"}
    if confidence not in valid_confidence:
        confidence = "low"

    return NextActionResult(
        action=action,
        reason=reason,
        confidence=confidence,
        decided_by="gpt",
    )


# ---------------------------------------------------------------------------
# GPT validation (double-check) — runs AFTER rules to validate their decision
# ---------------------------------------------------------------------------


async def _gpt_validate_rules_decision(
    ctx: NextActionContext,
    rules_result: NextActionResult,
    openai_client: AsyncOpenAI,
) -> NextActionResult:
    """Validate a rules engine decision by asking GPT for an independent assessment.

    If GPT agrees with the rules decision → keep it (confidence stays or improves).
    If GPT disagrees → escalate to human_review with both perspectives logged.

    Args:
        ctx: NextActionContext with all dimension outputs.
        rules_result: The decision made by the rules engine.
        openai_client: AsyncOpenAI client for the validation call.

    Returns:
        NextActionResult — either the original rules result (validated) or human_review.
    """
    ctx_dict = _build_context_dict(ctx)
    ctx_dict["rules_proposed_action"] = {
        "action": rules_result.action,
        "reason": rules_result.reason,
        "confidence": rules_result.confidence,
    }

    payload = json.dumps(ctx_dict, default=str)

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _GPT_VALIDATION_PROMPT},
                {
                    "role": "user",
                    "content": f"Rules engine proposed: {rules_result.action}. "
                    f"Validate this decision against the full context:\n{payload}",
                },
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )

        raw_content = response.choices[0].message.content or "{}"
        parsed = json.loads(raw_content)

        gpt_agrees = parsed.get("agrees", True)
        gpt_action = parsed.get("action", rules_result.action)
        gpt_reason = parsed.get("reason", "")
        gpt_confidence = parsed.get("confidence", "medium")

        # Validate vocabularies
        valid_actions = {
            "follow_up",
            "retry_call",
            "schedule_call",
            "close_lead",
            "human_review",
        }
        if gpt_action not in valid_actions:
            gpt_action = rules_result.action
            gpt_agrees = True  # Can't disagree with an invalid suggestion

        valid_confidence = {"high", "medium", "low"}
        if gpt_confidence not in valid_confidence:
            gpt_confidence = "medium"

        if gpt_agrees:
            logger.info(
                "next_action_gpt_validates_rules rules_action=%s gpt_action=%s gpt_reason=%s",
                rules_result.action,
                gpt_action,
                gpt_reason,
            )
            # Keep original rules result but note GPT validated it
            return NextActionResult(
                action=rules_result.action,
                reason=f"{rules_result.reason} [GPT validated: {gpt_reason}]",
                confidence=rules_result.confidence,
                decided_by="rules",
                next_action_at=rules_result.next_action_at,
                priority=rules_result.priority,
            )
        else:
            logger.warning(
                "next_action_gpt_disagrees_with_rules rules_action=%s gpt_action=%s gpt_reason=%s",
                rules_result.action,
                gpt_action,
                gpt_reason,
            )
            # GPT disagrees — escalate to human_review
            return NextActionResult(
                action="human_review",
                reason=(
                    f"Rules decided '{rules_result.action}' ({rules_result.reason}), "
                    f"but GPT recommends '{gpt_action}' ({gpt_reason}). "
                    f"Escalated for human review."
                ),
                confidence="low",
                decided_by="rules",
                next_action_at=rules_result.next_action_at,
                priority=rules_result.priority,
            )

    except Exception as exc:
        # Validation failed — trust the rules decision (graceful degradation)
        logger.warning(
            "next_action_gpt_validation_failed error=%s rules_action=%s",
            str(exc),
            rules_result.action,
        )
        return rules_result


# ---------------------------------------------------------------------------
# Pipeline entry point
# ---------------------------------------------------------------------------


async def run_next_action_pipeline(
    ctx: NextActionContext,
    openai_client: AsyncOpenAI,
) -> NextActionResult:
    """Evaluate rules in priority order; GPT always validates.

    Flow:
    1. Run rules engine (P1-P5) in priority order.
    2. If a rule matches → GPT validates the decision (double-check).
       - GPT agrees → keep the rules decision.
       - GPT disagrees → escalate to human_review.
    3. If no rule matches → GPT decides independently (fallback).

    GPT validation failures are non-fatal: if the validation call fails,
    the rules decision is trusted as-is (graceful degradation).

    Args:
        ctx: NextActionContext assembled from all dimension outputs + lead + client.
        openai_client: AsyncOpenAI client (used for validation and fallback).

    Returns:
        NextActionResult with action, reason, confidence, decided_by, next_action_at.
    """
    result = _evaluate_rules(ctx)

    if result is not None:
        logger.info(
            "next_action_rules_decision",
            action=result.action,
            decided_by=result.decided_by,
            confidence=result.confidence,
        )
        # Always validate rules decisions with GPT
        return await _gpt_validate_rules_decision(ctx, result, openai_client)

    # No rule matched — GPT decides independently
    logger.info("next_action_gpt_fallback_triggered")
    return await _gpt_fallback(ctx, openai_client)
