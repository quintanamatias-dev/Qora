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
