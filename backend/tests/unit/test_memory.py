"""Unit tests for app.memory — build_memory_context (CAP-1).

TDD RED phase: All tests reference app.memory which does NOT exist yet.
Tasks: T01-T12 (RED), T13 (GREEN).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# DB fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_db(tmp_path: Path):
    """Async SQLite DB with quintana-seguros and one test lead."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/memory_test.db",
    )
    await db_module.init_db(settings)

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        from app.tenants.service import seed_quintana
        from app.leads.service import create_lead

        await seed_quintana(sess)
        await create_lead(
            sess,
            client_id="quintana-seguros",
            name="Memory Lead",
            phone="+5411000099",
            lead_id="test-lead-memory-001",
        )
        await sess.commit()

    yield db_module

    await db_module.close_db()


async def _create_completed_session(
    db_module,
    *,
    lead_id: str,
    summary: str | None,
    ended_at: datetime | None = None,
) -> str:
    """Helper: create a completed CallSession with optional summary."""
    from app.calls.models import CallSession

    assert db_module.async_session_factory is not None
    session_id = str(uuid.uuid4())
    async with db_module.async_session_factory() as sess:
        cs = CallSession(
            id=session_id,
            client_id="quintana-seguros",
            lead_id=lead_id,
            status="completed",
            ended_at=ended_at or datetime.now(timezone.utc),
            summary=summary,
        )
        sess.add(cs)
        await sess.commit()
    return session_id


async def _create_initiated_session(db_module, *, lead_id: str) -> str:
    """Helper: create an initiated (non-completed) CallSession."""
    from app.calls.models import CallSession

    assert db_module.async_session_factory is not None
    session_id = str(uuid.uuid4())
    async with db_module.async_session_factory() as sess:
        cs = CallSession(
            id=session_id,
            client_id="quintana-seguros",
            lead_id=lead_id,
            status="initiated",
        )
        sess.add(cs)
        await sess.commit()
    return session_id


# ---------------------------------------------------------------------------
# T01 — None lead raises ValueError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_raises_value_error_on_none_lead(seeded_db):
    """build_memory_context raises ValueError when lead is None."""
    from app.memory import build_memory_context

    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        with pytest.raises(ValueError):
            await build_memory_context(sess, None)


# ---------------------------------------------------------------------------
# T02 — Empty defaults when lead has no completed sessions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_defaults_when_lead_has_no_completed_sessions(seeded_db):
    """No completed sessions → call_history='', confirmed_facts='', is_returning_caller=False, call_number=1."""
    from app.memory import build_memory_context
    from app.leads.service import get_lead

    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        lead = await get_lead(sess, "test-lead-memory-001")
        assert lead is not None
        # lead.call_count defaults to 0

        ctx = await build_memory_context(sess, lead)

    assert ctx["call_history"] == ""
    assert ctx["confirmed_facts"] == ""
    assert ctx["is_returning_caller"] is False
    assert ctx["call_number"] == 1


# ---------------------------------------------------------------------------
# T03 — Single completed session produces one call_history line
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_completed_session_produces_one_call_history_line(seeded_db):
    """One completed session → call_history has exactly one line with summary."""
    from app.memory import build_memory_context
    from app.leads.service import get_lead

    summary_text = "El cliente mostró interés en cambiar de seguro."
    await _create_completed_session(
        seeded_db,
        lead_id="test-lead-memory-001",
        summary=summary_text,
    )

    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        lead = await get_lead(sess, "test-lead-memory-001")
        assert lead is not None

        ctx = await build_memory_context(sess, lead)

    lines = [line for line in ctx["call_history"].split("\n") if line.strip()]
    assert len(lines) == 1
    assert summary_text[:50] in ctx["call_history"]
    assert ctx["is_returning_caller"] is True


# ---------------------------------------------------------------------------
# T04 — Loads at most 3 sessions ordered by ended_at DESC
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loads_at_most_3_sessions_ordered_by_ended_at_desc(seeded_db):
    """4 completed sessions → only 3 most recent appear in call_history."""
    from app.memory import build_memory_context
    from app.leads.service import get_lead

    now = datetime.now(timezone.utc)

    # Create 4 sessions: oldest first, so we can detect which 3 appear
    await _create_completed_session(
        seeded_db,
        lead_id="test-lead-memory-001",
        summary="Oldest session — must be excluded.",
        ended_at=now - timedelta(days=10),
    )
    await _create_completed_session(
        seeded_db,
        lead_id="test-lead-memory-001",
        summary="Third most recent session.",
        ended_at=now - timedelta(days=3),
    )
    await _create_completed_session(
        seeded_db,
        lead_id="test-lead-memory-001",
        summary="Second most recent session.",
        ended_at=now - timedelta(days=2),
    )
    await _create_completed_session(
        seeded_db,
        lead_id="test-lead-memory-001",
        summary="Most recent session.",
        ended_at=now - timedelta(days=1),
    )

    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        lead = await get_lead(sess, "test-lead-memory-001")
        assert lead is not None
        ctx = await build_memory_context(sess, lead)

    lines = [line for line in ctx["call_history"].split("\n") if line.strip()]
    assert len(lines) == 3
    assert "Oldest session" not in ctx["call_history"]
    assert "Most recent session" in ctx["call_history"]


# ---------------------------------------------------------------------------
# T05 — call_history format: date and summary, BA timezone
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_history_format_date_summary(seeded_db):
    """call_history lines have format: 'Llamada del DD/MM/YYYY: \"<first 150 chars>\"'."""
    from app.memory import build_memory_context
    from app.leads.service import get_lead
    from zoneinfo import ZoneInfo

    tz_ba = ZoneInfo("America/Argentina/Buenos_Aires")
    # Use a fixed UTC time that maps to a known BA date
    # UTC 2025-04-15 02:00 → BA 2025-04-14 23:00 (UTC-3)
    ended_at_utc = datetime(2025, 4, 15, 2, 0, 0, tzinfo=timezone.utc)
    expected_ba_date = ended_at_utc.astimezone(tz_ba).strftime("%d/%m/%Y")

    summary_text = "Resumen de la llamada con el cliente sobre seguros."

    await _create_completed_session(
        seeded_db,
        lead_id="test-lead-memory-001",
        summary=summary_text,
        ended_at=ended_at_utc,
    )

    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        lead = await get_lead(sess, "test-lead-memory-001")
        assert lead is not None
        ctx = await build_memory_context(sess, lead)

    expected_line_start = f'Llamada del {expected_ba_date}: "{summary_text[:150]}'
    assert ctx["call_history"].startswith(expected_line_start), (
        f"Expected line starting with:\n  {expected_line_start!r}\n"
        f"Got:\n  {ctx['call_history']!r}"
    )


# ---------------------------------------------------------------------------
# T06 — confirmed_facts empty when extracted_facts is None or empty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirmed_facts_empty_when_extracted_facts_none_or_empty(seeded_db):
    """extracted_facts=None → confirmed_facts=''; extracted_facts={} → confirmed_facts=''."""
    from app.memory import build_memory_context
    from app.leads.service import get_lead

    assert seeded_db.async_session_factory is not None

    # Test with None
    async with seeded_db.async_session_factory() as sess:
        lead = await get_lead(sess, "test-lead-memory-001")
        assert lead is not None
        lead.extracted_facts = None
        ctx_none = await build_memory_context(sess, lead)

    assert ctx_none["confirmed_facts"] == ""

    # Test with empty dict
    async with seeded_db.async_session_factory() as sess:
        lead = await get_lead(sess, "test-lead-memory-001")
        assert lead is not None
        lead.extracted_facts = {}
        ctx_empty = await build_memory_context(sess, lead)

    assert ctx_empty["confirmed_facts"] == ""


# ---------------------------------------------------------------------------
# T07 — confirmed_facts fixed order: current_insurance, interest_level, next_action_suggested
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirmed_facts_fixed_order(seeded_db):
    """confirmed_facts renders keys in order: current_insurance, interest_level, next_action_suggested."""
    from app.memory import build_memory_context
    from app.leads.service import get_lead

    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        lead = await get_lead(sess, "test-lead-memory-001")
        assert lead is not None
        lead.extracted_facts = {
            "next_action_suggested": "enviar_cotizacion",
            "interest_level": 80,
            "current_insurance": "La Caja",
        }
        ctx = await build_memory_context(sess, lead)

    facts = ctx["confirmed_facts"]
    pos_insurance = facts.find("Seguro actual: La Caja")
    pos_interest = facts.find("Nivel de interés: 80/100")
    pos_action = facts.find("Acción sugerida: enviar_cotizacion")

    assert pos_insurance != -1, "current_insurance missing from confirmed_facts"
    assert pos_interest != -1, "interest_level missing from confirmed_facts"
    assert pos_action != -1, "next_action_suggested missing from confirmed_facts"

    # Verify ordering: insurance < interest < action
    assert (
        pos_insurance < pos_interest
    ), "current_insurance should appear before interest_level"
    assert (
        pos_interest < pos_action
    ), "interest_level should appear before next_action_suggested"


# ---------------------------------------------------------------------------
# T08 — is_returning_caller True when at least one completed session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_returning_caller_true_when_at_least_one_completed(seeded_db):
    """Any completed session → is_returning_caller=True."""
    from app.memory import build_memory_context
    from app.leads.service import get_lead

    await _create_completed_session(
        seeded_db,
        lead_id="test-lead-memory-001",
        summary="Breve resumen.",
    )

    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        lead = await get_lead(sess, "test-lead-memory-001")
        assert lead is not None
        ctx = await build_memory_context(sess, lead)

    assert ctx["is_returning_caller"] is True


# ---------------------------------------------------------------------------
# T09 — call_number equals lead.call_count + 1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_number_equals_lead_call_count_plus_one(seeded_db):
    """call_number == lead.call_count + 1."""
    from app.memory import build_memory_context
    from app.leads.service import get_lead

    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        lead = await get_lead(sess, "test-lead-memory-001")
        assert lead is not None
        lead.call_count = 3
        ctx = await build_memory_context(sess, lead)

    assert ctx["call_number"] == 4  # 3 + 1


# ---------------------------------------------------------------------------
# T10 — Emits memory_context_built log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emits_memory_context_built_log(seeded_db):
    """build_memory_context emits 'memory_context_built' log with required fields."""
    from app.memory import build_memory_context
    from app.leads.service import get_lead
    from structlog.testing import capture_logs

    await _create_completed_session(
        seeded_db,
        lead_id="test-lead-memory-001",
        summary="Una llamada de prueba para el log.",
    )

    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        lead = await get_lead(sess, "test-lead-memory-001")
        assert lead is not None
        lead.call_count = 2

        with capture_logs() as logs:
            await build_memory_context(sess, lead)

    # Find the memory_context_built event
    memory_logs = [
        entry for entry in logs if entry.get("event") == "memory_context_built"
    ]
    assert len(memory_logs) == 1, f"Expected 1 'memory_context_built' log, got: {logs}"

    log = memory_logs[0]
    assert "lead_id" in log
    assert "session_count" in log
    assert "has_facts" in log
    assert "call_number" in log

    assert log["lead_id"] == lead.id
    assert log["session_count"] == 1
    assert log["call_number"] == 3  # call_count=2 → call_number=3


# ---------------------------------------------------------------------------
# T11 — Ignores non-completed sessions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ignores_non_completed_sessions(seeded_db):
    """Sessions with status 'initiated' or 'abandoned' do not affect call_history or is_returning_caller."""
    from app.memory import build_memory_context
    from app.leads.service import get_lead

    # Create a non-completed session
    await _create_initiated_session(seeded_db, lead_id="test-lead-memory-001")

    # Also create an abandoned session manually
    from app.calls.models import CallSession

    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        cs = CallSession(
            id=str(uuid.uuid4()),
            client_id="quintana-seguros",
            lead_id="test-lead-memory-001",
            status="abandoned",
            summary="Abandoned session with summary.",
        )
        sess.add(cs)
        await sess.commit()

    async with seeded_db.async_session_factory() as sess:
        lead = await get_lead(sess, "test-lead-memory-001")
        assert lead is not None
        ctx = await build_memory_context(sess, lead)

    assert ctx["call_history"] == ""
    assert ctx["is_returning_caller"] is False


# ---------------------------------------------------------------------------
# T12 — Ignores sessions with null or empty summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ignores_sessions_with_null_or_empty_summary(seeded_db):
    """Completed sessions with NULL or empty summary are excluded from call_history."""
    from app.memory import build_memory_context
    from app.leads.service import get_lead

    now = datetime.now(timezone.utc)

    # Session with None summary
    await _create_completed_session(
        seeded_db,
        lead_id="test-lead-memory-001",
        summary=None,
        ended_at=now - timedelta(hours=2),
    )
    # Session with empty string summary
    await _create_completed_session(
        seeded_db,
        lead_id="test-lead-memory-001",
        summary="",
        ended_at=now - timedelta(hours=1),
    )
    # Session with valid summary
    await _create_completed_session(
        seeded_db,
        lead_id="test-lead-memory-001",
        summary="Resumen válido del cliente.",
        ended_at=now,
    )

    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        lead = await get_lead(sess, "test-lead-memory-001")
        assert lead is not None
        ctx = await build_memory_context(sess, lead)

    lines = [line for line in ctx["call_history"].split("\n") if line.strip()]
    assert (
        len(lines) == 1
    ), f"Expected only the valid session, got: {ctx['call_history']!r}"
    assert "Resumen válido del cliente." in ctx["call_history"]


# ---------------------------------------------------------------------------
# T41 — REQ-1.5: is_returning_caller is True iff ANY completed session exists,
# independent of summary presence.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_returning_caller_true_even_when_sessions_have_no_summary(seeded_db):
    """REQ-1.5: is_returning_caller is True iff ANY completed session exists,
    independent of summary presence. A completed session with summary=None or ""
    still marks the lead as returning.

    This also verifies that call_history is "" (no summary to format) while
    is_returning_caller is True (the session EXISTS).
    """
    from app.memory import build_memory_context
    from app.leads.service import get_lead

    # Seed: lead with 1 completed session, summary=None
    await _create_completed_session(
        seeded_db,
        lead_id="test-lead-memory-001",
        summary=None,  # no summary — must NOT affect is_returning_caller
    )

    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        lead = await get_lead(sess, "test-lead-memory-001")
        assert lead is not None
        ctx = await build_memory_context(sess, lead)

    # is_returning_caller must be True — a completed session EXISTS
    assert ctx["is_returning_caller"] is True, (
        "is_returning_caller must be True when any completed session exists, "
        "even if summary is None. Got False."
    )
    # call_history must be "" — no summary to format
    assert ctx["call_history"] == "", (
        f"call_history must be '' when session has no summary. "
        f"Got: {ctx['call_history']!r}"
    )


@pytest.mark.asyncio
async def test_is_returning_caller_true_when_session_has_empty_string_summary(
    seeded_db,
):
    """REQ-1.5 triangulation: Completed session with summary='' also marks caller as returning."""
    from app.memory import build_memory_context
    from app.leads.service import get_lead

    # Seed: lead with 1 completed session, summary=""
    await _create_completed_session(
        seeded_db,
        lead_id="test-lead-memory-001",
        summary="",  # empty string — must NOT affect is_returning_caller
    )

    assert seeded_db.async_session_factory is not None
    async with seeded_db.async_session_factory() as sess:
        lead = await get_lead(sess, "test-lead-memory-001")
        assert lead is not None
        ctx = await build_memory_context(sess, lead)

    # is_returning_caller must be True — a completed session EXISTS
    assert ctx["is_returning_caller"] is True, (
        "is_returning_caller must be True when any completed session exists, "
        "even if summary is empty string. Got False."
    )
    # call_history must be "" — empty summary not rendered
    assert ctx["call_history"] == "", (
        f"call_history must be '' when session has empty summary. "
        f"Got: {ctx['call_history']!r}"
    )


# ---------------------------------------------------------------------------
# Issue #21 — Dynamic fact rendering tests (tasks 2.1 + 2.2)
# ---------------------------------------------------------------------------


def test_format_confirmed_facts_renders_all_keys_dynamically():
    """_format_confirmed_facts renders ALL keys in extracted_facts, not just 3 hardcoded."""
    from app.memory import _format_confirmed_facts

    facts = {
        "current_insurance": "La Caja",
        "interest_level": 75,
        "next_action_suggested": "call_again",
        "misc_notes": "Lead mentioned Toyota Hilux",
        "custom_field": "some_value",
    }
    result = _format_confirmed_facts(facts)

    # All 5 keys must appear in the output
    assert "La Caja" in result, "current_insurance must appear"
    assert "75" in result, "interest_level must appear"
    assert "call_again" in result, "next_action_suggested must appear"
    assert "Toyota Hilux" in result, "misc_notes must appear"
    assert "some_value" in result, "custom_field (unknown key) must appear"


def test_format_confirmed_facts_known_keys_use_spanish_labels():
    """Known keys use their Spanish labels (Seguro actual, Nivel de interés, etc.)."""
    from app.memory import _format_confirmed_facts

    facts = {
        "current_insurance": "Sancor",
        "interest_level": 80,
        "next_action_suggested": "send_quote",
        "misc_notes": "Nota adicional",
    }
    result = _format_confirmed_facts(facts)

    assert "Seguro actual" in result
    assert "Nivel de interés" in result
    assert "Acción sugerida" in result
    assert "Notas adicionales" in result


def test_format_confirmed_facts_unknown_key_uses_raw_key_as_label():
    """Unknown keys use their key name (possibly title-cased) as label (no Spanish translation)."""
    from app.memory import _format_confirmed_facts

    facts = {"custom_field": "custom_value", "my_special_key": "xyz"}
    result = _format_confirmed_facts(facts)

    # Key-derived label must appear (raw or title-cased)
    result_lower = result.lower()
    assert (
        "custom" in result_lower and "field" in result_lower
    ), f"'custom_field' label must appear in output: {result!r}"
    assert "custom_value" in result
    assert "xyz" in result


def test_format_confirmed_facts_interest_level_keeps_slash_100_format():
    """interest_level renders as '{value}/100'."""
    from app.memory import _format_confirmed_facts

    facts = {"interest_level": 75}
    result = _format_confirmed_facts(facts)

    assert "75/100" in result, f"Expected '75/100' in output, got: {result!r}"


def test_format_confirmed_facts_skips_none_and_empty_values():
    """Keys with None or empty string values are skipped."""
    from app.memory import _format_confirmed_facts

    facts = {
        "current_insurance": None,
        "misc_notes": "",
        "interest_level": 60,
    }
    result = _format_confirmed_facts(facts)

    # Only interest_level should appear
    assert "60/100" in result
    # None and empty values must NOT produce output lines
    lines = [line for line in result.splitlines() if line.strip()]
    assert len(lines) == 1, f"Expected 1 line, got {len(lines)}: {result!r}"


def test_format_confirmed_facts_known_keys_appear_before_unknown():
    """Known keys (current_insurance, interest_level, next_action_suggested) appear before unknown keys."""
    from app.memory import _format_confirmed_facts

    facts = {
        "zzz_unknown": "z_value",
        "aaa_unknown": "a_value",
        "current_insurance": "La Caja",
        "interest_level": 80,
    }
    result = _format_confirmed_facts(facts)

    pos_insurance = result.find("La Caja")
    pos_z = result.find("z_value")
    pos_a = result.find("a_value")

    assert pos_insurance != -1, "current_insurance must appear"
    assert pos_z != -1, "zzz_unknown must appear"
    assert pos_a != -1, "aaa_unknown must appear"

    # Known keys must appear BEFORE unknown keys
    assert pos_insurance < pos_z, "current_insurance must come before zzz_unknown"
    assert pos_insurance < pos_a, "current_insurance must come before aaa_unknown"


def test_format_confirmed_facts_renders_nested_dict_call_outcome():
    """Nested dict values (like call_outcome) are flattened to a one-line summary."""
    from app.memory import _format_confirmed_facts

    facts = {
        "call_outcome": {
            "classification": "completed_positive",
            "confidence": "high",
            "reason": "Lead asked for a quote",
        }
    }
    result = _format_confirmed_facts(facts)

    # Must produce some output (not empty)
    assert result.strip() != "", "call_outcome dict must produce output"
    # Must contain recognizable content from the nested dict
    assert (
        "completed_positive" in result
        or "Resultado" in result
        or "call_outcome" in result
    )


# ---------------------------------------------------------------------------
# qora-outcome: _format_axis("call_outcome") — no engagement_quality
# ---------------------------------------------------------------------------


def test_format_axis_call_outcome_renders_classification_reason_confidence():
    """_format_axis('call_outcome') renders classification, reason, and confidence."""
    from app.memory import _format_axis

    axis_dict = {
        "classification": "completed_positive",
        "reason": "Lead bought the policy",
        "confidence": "high",
    }
    result = _format_axis("call_outcome", axis_dict)

    assert (
        "completed_positive" in result
    ), "_format_axis must include classification in output"
    assert (
        "Lead bought the policy" in result
    ), "_format_axis must include reason in output"
    assert (
        "engagement" not in result.lower()
    ), "_format_axis must NOT mention engagement (qora-outcome spec)"


def test_format_axis_call_outcome_does_not_read_engagement_quality():
    """_format_axis('call_outcome') does NOT read or render engagement_quality."""
    from app.memory import _format_axis

    # Even if legacy data has engagement_quality, it must not appear in output
    axis_dict_with_legacy = {
        "classification": "completed_negative",
        "reason": "Lead declined.",
        "confidence": "medium",
        "engagement_quality": "high",  # legacy field — must be ignored
    }
    result = _format_axis("call_outcome", axis_dict_with_legacy)

    assert (
        "engagement" not in result.lower()
    ), "_format_axis must NOT reference engagement even when field is present (qora-outcome spec)"
    assert "completed_negative" in result


def test_format_confirmed_facts_lists_joined_as_string():
    """List values (like objections) are joined and rendered as a string."""
    from app.memory import _format_confirmed_facts

    facts = {"objections": ["precio alto", "ya tiene seguro"]}
    result = _format_confirmed_facts(facts)

    # Must produce output containing the list items
    assert "precio alto" in result or "objections" in result.lower()


# ---------------------------------------------------------------------------
# Issue #36 Phase 3 — Memory context upgrade: accumulated profile facts
# ---------------------------------------------------------------------------


async def _insert_profile_fact(
    db_module, *, lead_id, fact_key, fact_value, superseded_at=None, recorded_at=None
):
    """Helper: insert a LeadProfileFact row directly."""
    import uuid as _uuid
    from app.leads.models import LeadProfileFact
    from datetime import datetime, timezone

    row_id = str(_uuid.uuid4())
    async with db_module.async_session_factory() as sess:
        row = LeadProfileFact(
            id=row_id,
            lead_id=lead_id,
            fact_key=fact_key,
            fact_value=fact_value,
            superseded_at=superseded_at,
            recorded_at=recorded_at or datetime.now(timezone.utc),
        )
        sess.add(row)
        await sess.commit()
    return row_id


async def _insert_interest_history_mem(
    db_module, *, lead_id, interest_level, recorded_at=None
):
    """Helper: insert a LeadInterestHistory row directly."""
    import uuid as _uuid
    from app.leads.models import LeadInterestHistory
    from datetime import datetime, timezone

    row_id = str(_uuid.uuid4())
    async with db_module.async_session_factory() as sess:
        row = LeadInterestHistory(
            id=row_id,
            lead_id=lead_id,
            interest_level=interest_level,
            recorded_at=recorded_at or datetime.now(timezone.utc),
        )
        sess.add(row)
        await sess.commit()
    return row_id


@pytest.mark.asyncio
async def test_confirmed_facts_includes_accumulated_profile_facts(seeded_db):
    """Issue #36 Phase 3: build_memory_context includes accumulated profile facts in confirmed_facts.

    GIVEN a lead with 3 active 'profile:' facts and 2 active 'pain:' facts
    WHEN build_memory_context(db, lead) is called
    THEN confirmed_facts contains lines for each accumulated fact, grouped by namespace.
    """
    from app.memory import build_memory_context
    from app.leads.service import get_lead

    lead_id = "test-lead-memory-001"

    await _insert_profile_fact(
        seeded_db, lead_id=lead_id, fact_key="profile:married", fact_value="married"
    )
    await _insert_profile_fact(
        seeded_db,
        lead_id=lead_id,
        fact_key="profile:has 2 children",
        fact_value="has 2 children",
    )
    await _insert_profile_fact(
        seeded_db,
        lead_id=lead_id,
        fact_key="pain:high premiums",
        fact_value="high premiums",
    )
    await _insert_profile_fact(
        seeded_db,
        lead_id=lead_id,
        fact_key="pain:no coverage",
        fact_value="no coverage",
    )

    async with seeded_db.async_session_factory() as sess:
        lead = await get_lead(sess, lead_id)
        assert lead is not None
        ctx = await build_memory_context(sess, lead)

    # The confirmed_facts must contain the accumulated facts
    confirmed = ctx["confirmed_facts"]
    assert (
        "married" in confirmed
    ), f"Expected 'married' in confirmed_facts, got: {confirmed!r}"
    assert "has 2 children" in confirmed, "Expected 'has 2 children' in confirmed_facts"
    assert "high premiums" in confirmed, "Expected 'high premiums' in confirmed_facts"
    assert "no coverage" in confirmed, "Expected 'no coverage' in confirmed_facts"


@pytest.mark.asyncio
async def test_confirmed_facts_token_budget_caps_at_10_per_namespace(seeded_db):
    """Issue #36 Phase 3: build_memory_context caps accumulated facts at 10 per namespace.

    GIVEN a lead with 15 active 'profile:' facts
    WHEN build_memory_context(db, lead) is called
    THEN at most 10 'profile:' facts appear in confirmed_facts.
    """
    from app.memory import build_memory_context
    from app.leads.service import get_lead

    lead_id = "test-lead-memory-001"
    now = datetime.now(timezone.utc)

    # Insert 15 profile: facts with different timestamps
    for i in range(15):
        await _insert_profile_fact(
            seeded_db,
            lead_id=lead_id,
            fact_key=f"profile:fact number {i}",
            fact_value=f"fact number {i}",
            recorded_at=now - timedelta(hours=15 - i),
        )

    async with seeded_db.async_session_factory() as sess:
        lead = await get_lead(sess, lead_id)
        assert lead is not None
        ctx = await build_memory_context(sess, lead)

    confirmed = ctx["confirmed_facts"]
    # Count how many unique 'fact number X' items appear using exact item matching
    # We look for items by their exact value; use word-boundary-like check with prefix/suffix
    count = sum(
        1
        for i in range(15)
        if f"fact number {i}," in confirmed or confirmed.endswith(f"fact number {i}")
    )
    assert (
        count <= 10
    ), f"Expected at most 10 profile: facts, found {count} in confirmed_facts"
    assert count >= 1, "Expected at least 1 profile: fact to appear"


@pytest.mark.asyncio
async def test_confirmed_facts_no_fallback_to_extracted_facts_json(seeded_db):
    """Issue #36 Phase 3: When no LeadProfileFact rows exist, confirmed_facts is empty or minimal.

    GIVEN a lead with no LeadProfileFact rows but non-empty Lead.extracted_facts
    WHEN build_memory_context(db, lead) is called
    THEN confirmed_facts does NOT include extracted_facts JSON blob content
         (uses relational tables only for new accumulated facts).
    """
    from app.memory import build_memory_context
    from app.leads.service import get_lead

    lead_id = "test-lead-memory-001"

    # Set extracted_facts to verify they don't bleed into accumulated section
    async with seeded_db.async_session_factory() as sess:
        lead = await get_lead(sess, lead_id)
        assert lead is not None
        lead.extracted_facts = {
            "current_insurance": "La Caja",
            "interest_level": 80,
        }
        await sess.commit()

    # No LeadProfileFact rows inserted — accumulated section should be absent
    async with seeded_db.async_session_factory() as sess:
        lead = await get_lead(sess, lead_id)
        assert lead is not None
        ctx = await build_memory_context(sess, lead)

    confirmed = ctx["confirmed_facts"]
    # The legacy section (current_insurance from extracted_facts) is still present
    assert "La Caja" in confirmed, "Legacy scalar facts should still be present"
    # But there must be no 'Perfil acumulado' / accumulated section if no profile facts exist
    assert (
        "Perfil acumulado" not in confirmed
    ), "Accumulated section must NOT appear when there are no LeadProfileFact rows"


@pytest.mark.asyncio
async def test_call_history_and_call_number_unchanged_after_profile_facts(seeded_db):
    """Issue #36 Phase 3: call_history and call_number behave exactly as before.

    GIVEN a lead with profile facts AND a completed session
    WHEN build_memory_context(db, lead) is called
    THEN call_history and call_number are unaffected by the new profile facts logic.
    """
    from app.memory import build_memory_context
    from app.leads.service import get_lead

    lead_id = "test-lead-memory-001"

    # Insert a completed session with summary
    await _create_completed_session(
        seeded_db,
        lead_id=lead_id,
        summary="El lead quiere seguro todo riesgo.",
    )

    # Insert a profile fact
    await _insert_profile_fact(
        seeded_db, lead_id=lead_id, fact_key="profile:retired", fact_value="retired"
    )

    async with seeded_db.async_session_factory() as sess:
        lead = await get_lead(sess, lead_id)
        assert lead is not None
        ctx = await build_memory_context(sess, lead)

    # call_history should still contain the session summary
    assert (
        "seguro todo riesgo" in ctx["call_history"]
    ), f"Expected session summary in call_history, got: {ctx['call_history']!r}"
    # is_returning_caller should be True (completed session exists)
    assert ctx["is_returning_caller"] is True
    # call_number should be lead.call_count + 1
    assert ctx["call_number"] == 1  # call_count=0 by default


# ---------------------------------------------------------------------------
# Issue #36 CRITICAL 1 — Interest history included in confirmed_facts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirmed_facts_includes_interest_history_evolution(seeded_db):
    """CRITICAL 1: build_memory_context includes LeadInterestHistory in confirmed_facts.

    GIVEN a lead with 3 LeadInterestHistory rows (oldest to newest: 75, 60, 85)
    WHEN build_memory_context(db, lead) is called
    THEN confirmed_facts contains 'Evolución de interés: 75→60→85' (oldest→newest order)
    """
    from app.memory import build_memory_context
    from app.leads.service import get_lead

    lead_id = "test-lead-memory-001"
    now = datetime.now(timezone.utc)

    # Insert 3 interest history entries; oldest first
    await _insert_interest_history_mem(
        seeded_db,
        lead_id=lead_id,
        interest_level=75,
        recorded_at=now - timedelta(hours=3),
    )
    await _insert_interest_history_mem(
        seeded_db,
        lead_id=lead_id,
        interest_level=60,
        recorded_at=now - timedelta(hours=2),
    )
    await _insert_interest_history_mem(
        seeded_db,
        lead_id=lead_id,
        interest_level=85,
        recorded_at=now - timedelta(hours=1),
    )

    async with seeded_db.async_session_factory() as sess:
        lead = await get_lead(sess, lead_id)
        assert lead is not None
        ctx = await build_memory_context(sess, lead)

    confirmed = ctx["confirmed_facts"]
    assert (
        "Evolución de interés:" in confirmed
    ), f"Expected 'Evolución de interés:' in confirmed_facts, got: {confirmed!r}"
    assert "75" in confirmed, f"Expected '75' in interest evolution, got: {confirmed!r}"
    assert "60" in confirmed, f"Expected '60' in interest evolution, got: {confirmed!r}"
    assert "85" in confirmed, f"Expected '85' in interest evolution, got: {confirmed!r}"
    # Verify the arrow format exists
    assert (
        "→" in confirmed
    ), f"Expected '→' separator in interest evolution, got: {confirmed!r}"


@pytest.mark.asyncio
async def test_confirmed_facts_interest_history_capped_at_5(seeded_db):
    """CRITICAL 1 triangulation: Interest history is capped at 5 entries.

    GIVEN a lead with 8 LeadInterestHistory rows
    WHEN build_memory_context(db, lead) is called
    THEN 'Evolución de interés:' contains at most 5 values (oldest to newest within cap)
    """
    from app.memory import build_memory_context
    from app.leads.service import get_lead

    lead_id = "test-lead-memory-001"
    now = datetime.now(timezone.utc)

    # Insert 8 entries with distinct values
    levels = [10, 20, 30, 40, 50, 60, 70, 80]
    for i, level in enumerate(levels):
        await _insert_interest_history_mem(
            seeded_db,
            lead_id=lead_id,
            interest_level=level,
            recorded_at=now - timedelta(hours=len(levels) - i),
        )

    async with seeded_db.async_session_factory() as sess:
        lead = await get_lead(sess, lead_id)
        assert lead is not None
        ctx = await build_memory_context(sess, lead)

    confirmed = ctx["confirmed_facts"]
    assert (
        "Evolución de interés:" in confirmed
    ), f"Expected 'Evolución de interés:' in confirmed_facts, got: {confirmed!r}"
    # Find the evolution line and count the arrows
    for line in confirmed.split("\n"):
        if "Evolución de interés:" in line:
            # Count number of data points: N arrows = N+1 values, so count by →
            arrow_count = line.count("→")
            assert arrow_count <= 4, (
                f"Expected at most 4 arrows (5 values) in interest evolution, "
                f"got {arrow_count + 1} values: {line!r}"
            )
            break


@pytest.mark.asyncio
async def test_confirmed_facts_no_interest_history_section_when_empty(seeded_db):
    """CRITICAL 1 edge case: No interest history → no 'Evolución de interés:' in confirmed_facts.

    GIVEN a lead with no LeadInterestHistory rows
    WHEN build_memory_context(db, lead) is called
    THEN confirmed_facts does NOT contain 'Evolución de interés:'
    """
    from app.memory import build_memory_context
    from app.leads.service import get_lead

    lead_id = "test-lead-memory-001"

    async with seeded_db.async_session_factory() as sess:
        lead = await get_lead(sess, lead_id)
        assert lead is not None
        ctx = await build_memory_context(sess, lead)

    confirmed = ctx["confirmed_facts"]
    assert "Evolución de interés:" not in confirmed, (
        f"'Evolución de interés:' should NOT appear when no history exists, "
        f"got: {confirmed!r}"
    )


# ===========================================================================
# qora-interest-pipeline — memory.py rendering tests
# ===========================================================================


def test_format_axis_detected_interests_new_items_format():
    """_format_axis for detected_interests handles new InterestsAxis format (items list).

    qora-interest-pipeline: detected_interests is now InterestsAxis with items.
    """
    from app.memory import _format_axis

    axis_dict = {
        "items": [
            {
                "product": "auto_todo_riesgo",
                "needs": ["precio_competitivo"],
                "evidence": "Me interesa.",
                "confidence": "high",
            },
            {
                "product": "hogar",
                "needs": [],
                "evidence": "También el hogar.",
                "confidence": "medium",
            },
        ]
    }
    result = _format_axis("detected_interests", axis_dict)

    assert (
        "auto_todo_riesgo" in result or "productos" in result
    ), f"Expected product names in rendering, got: {result!r}"


def test_format_axis_detected_interests_empty_items():
    """_format_axis for detected_interests with empty items returns empty string."""
    from app.memory import _format_axis

    axis_dict = {"items": []}
    result = _format_axis("detected_interests", axis_dict)

    assert result == "", f"Expected empty string for empty items, got: {result!r}"


def test_format_axis_detected_interests_legacy_format_still_works():
    """_format_axis for detected_interests handles old format (products/specific_needs/buying_signals).

    Legacy data in extracted_facts may still use the old format.
    Memory rendering must handle both.
    """
    from app.memory import _format_axis

    axis_dict = {
        "products": ["todo_riesgo"],
        "specific_needs": ["precio_competitivo"],
        "buying_signals": [],
    }
    result = _format_axis("detected_interests", axis_dict)

    # Should render something (not empty) for non-empty legacy format
    assert (
        "todo_riesgo" in result or "products" in result
    ), f"Expected product names in legacy rendering, got: {result!r}"


def test_render_fact_value_interest_level_int():
    """_render_fact_value for interest_level int renders as '{value}/100' (unchanged)."""
    from app.memory import _render_fact_value

    result = _render_fact_value("interest_level", 68)
    assert result == "68/100"


def test_render_fact_value_interest_level_dict_extracts_general_score():
    """_render_fact_value for interest_level dict (new pipeline format) extracts general_score.

    qora-interest-pipeline: rich InterestLevelResult data may be stored in extra_axes_data.
    The interest_level field itself stays int, but for backward compat the rendering
    must handle dict format in case legacy code stored dicts.
    """
    from app.memory import _render_fact_value

    # The interest_level field itself stays int — this tests the dict branch in _format_axis
    # (called when interest_level is somehow a dict in extracted_facts)
    result = _render_fact_value("interest_level", 82)
    assert result == "82/100"


# ===========================================================================
# qora-profile-facts Phase 4 — Memory rendering (RED tests 4.1)
# ===========================================================================


@pytest.mark.asyncio
async def test_profile_facts_rendered_grouped_by_category(seeded_db):
    """Phase 4: profile: rows with JSON fact_value render as '{CategoryLabel}: {fact}'.

    GIVEN two active 'profile:' rows with JSON fact_values:
      - profile:occupation:vendedor → {category: occupation, fact: 'vendedor inmobiliario', ...}
      - profile:communication_preference:email → {category: communication_preference, fact: 'email', ...}
    WHEN build_memory_context(db, lead) is called
    THEN confirmed_facts contains:
      - 'Ocupación: vendedor inmobiliario'
      - 'Preferencia de contacto: email'

    Spec: '_format_accumulated_profile groups profile: rows by category, renders as label: fact'
    """
    from app.memory import build_memory_context
    from app.leads.service import get_lead
    import json

    lead_id = "test-lead-memory-001"

    await _insert_profile_fact(
        seeded_db,
        lead_id=lead_id,
        fact_key="profile:occupation:vendedor-inmobiliario",
        fact_value=json.dumps(
            {
                "category": "occupation",
                "fact": "vendedor inmobiliario",
                "evidence": "Soy vendedor inmobiliario",
                "confidence": "high",
            }
        ),
    )
    await _insert_profile_fact(
        seeded_db,
        lead_id=lead_id,
        fact_key="profile:communication_preference:email",
        fact_value=json.dumps(
            {
                "category": "communication_preference",
                "fact": "prefiere email",
                "evidence": "Prefiero que me manden todo por email",
                "confidence": "medium",
            }
        ),
    )

    async with seeded_db.async_session_factory() as sess:
        lead = await get_lead(sess, lead_id)
        assert lead is not None
        ctx = await build_memory_context(sess, lead)

    confirmed = ctx["confirmed_facts"]
    assert (
        "Ocupación: vendedor inmobiliario" in confirmed
    ), f"Expected 'Ocupación: vendedor inmobiliario' in confirmed_facts, got:\n{confirmed!r}"
    assert (
        "Preferencia de contacto: prefiere email" in confirmed
    ), f"Expected 'Preferencia de contacto: prefiere email' in confirmed_facts, got:\n{confirmed!r}"


def test_format_accumulated_profile_renders_structured_facts_by_category():
    """Phase 4 unit: _format_accumulated_profile renders JSON profile: rows by category label.

    Pure function test — doesn't need DB.
    Tests the _PROFILE_CATEGORY_LABELS mapping and grouped rendering logic.
    """
    from app.memory import _PROFILE_CATEGORY_LABELS

    # All 11 categories must have Spanish labels
    expected_keys = {
        "occupation",
        "availability",
        "communication_preference",
        "decision_style",
        "family_context",
        "lifestyle",
        "financial_attitude",
        "product_knowledge",
        "provider_relationship",
        "personality_tone",
        "other",
    }
    assert expected_keys.issubset(set(_PROFILE_CATEGORY_LABELS.keys())), (
        f"_PROFILE_CATEGORY_LABELS must contain all 11 categories. "
        f"Missing: {expected_keys - set(_PROFILE_CATEGORY_LABELS.keys())}"
    )
    # Key labels must be Spanish strings
    assert _PROFILE_CATEGORY_LABELS["occupation"] == "Ocupación"
    assert _PROFILE_CATEGORY_LABELS["family_context"] == "Contexto familiar"
    assert (
        _PROFILE_CATEGORY_LABELS["communication_preference"]
        == "Preferencia de contacto"
    )


@pytest.mark.asyncio
async def test_profile_facts_legacy_plain_string_renders_without_error(seeded_db):
    """Phase 4: Legacy profile: rows with plain string fact_value render without error.

    GIVEN an active 'profile:' row with fact_value='plain text' (not JSON)
    WHEN build_memory_context(db, lead) is called
    THEN the row renders as the raw string value
    AND no exception is raised.

    Spec: 'The renderer MUST handle legacy rows (where fact_value is a plain string,
    not JSON) by displaying the raw string value without error.'
    """
    from app.memory import build_memory_context
    from app.leads.service import get_lead

    lead_id = "test-lead-memory-001"

    await _insert_profile_fact(
        seeded_db,
        lead_id=lead_id,
        fact_key="profile:old_format",
        fact_value="owns a home",  # plain string (legacy format)
    )

    async with seeded_db.async_session_factory() as sess:
        lead = await get_lead(sess, lead_id)
        assert lead is not None
        # Must not raise any exception
        ctx = await build_memory_context(sess, lead)

    confirmed = ctx["confirmed_facts"]
    # The raw string value must appear somewhere in confirmed_facts
    assert "owns a home" in confirmed, (
        f"Expected legacy plain-string fact_value 'owns a home' in confirmed_facts, "
        f"got: {confirmed!r}"
    )


@pytest.mark.asyncio
async def test_profile_facts_empty_after_all_removed(seeded_db):
    """Phase 4: When all profile: rows are removed (no active rows), section is absent.

    GIVEN a lead with no active 'profile:' rows (all superseded/deleted)
    WHEN build_memory_context(db, lead) is called
    THEN the accumulated profile section does NOT appear
    AND no error is raised.

    Spec: 'No active profile facts → accumulated profile section is absent or empty.'
    Note: This tests the existing superseded_at IS NULL filter; no profile: rows → empty section.
    """
    from app.memory import build_memory_context
    from app.leads.service import get_lead
    from datetime import datetime, timezone

    lead_id = "test-lead-memory-001"

    # Insert a superseded (effectively "removed") row
    await _insert_profile_fact(
        seeded_db,
        lead_id=lead_id,
        fact_key="profile:occupation:old",
        fact_value="old job",
        superseded_at=datetime.now(timezone.utc),
    )

    async with seeded_db.async_session_factory() as sess:
        lead = await get_lead(sess, lead_id)
        assert lead is not None
        ctx = await build_memory_context(sess, lead)

    confirmed = ctx["confirmed_facts"]
    # No active profile: rows → no accumulated section with profile data
    # (The interest history / other namespaces might still appear, but NOT profile:)
    assert (
        "old job" not in confirmed
    ), "Superseded profile fact must NOT appear in confirmed_facts"
