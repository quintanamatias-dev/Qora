"""Unit tests for the post-call summarizer (CAP-4).

Covers:
- 0 turns → no GPT call, summary stays null
- GPT failure → logged, no exception raised, session stays completed
- do_not_call flag set when next_action_suggested = "do_not_call"

Mocks the OpenAI client — does NOT make real API calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_db(tmp_path: Path):
    """Isolated SQLite DB with quintana-seguros + one test lead."""
    from app.core.config import Settings
    from app.core import database as db_module

    settings = Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/summarizer_test.db",
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
            name="Summary Lead",
            phone="+5411000003",
            lead_id="test-lead-sum-001",
        )
        await sess.commit()

    yield db_module

    await db_module.close_db()


async def _create_session(
    db_module, *, with_turns: list[tuple[str, str]] | None = None
) -> str:
    """Helper: create a CallSession (status=completed) with optional transcript turns."""
    from app.calls.service import create_session, add_transcript_turn

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as sess:
        cs = await create_session(
            sess,
            client_id="quintana-seguros",
            lead_id="test-lead-sum-001",
        )
        # Mark as completed so summarizer can find it
        cs.status = "completed"

        if with_turns:
            for role, content in with_turns:
                await add_transcript_turn(sess, cs.id, role, content)

        await sess.commit()
        return cs.id


def _make_openai_response(payload: dict) -> MagicMock:
    """Create a mock OpenAI chat completion response."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps(payload)
    return mock_response


# ---------------------------------------------------------------------------
# CAP-4: 0 turns → no GPT call
# ---------------------------------------------------------------------------


async def test_summarizer_skips_when_no_turns(seeded_db):
    """generate_summary_and_facts() with 0 turns → no GPT call, session summary=None."""
    from app.summarizer import generate_summary_and_facts
    from app.calls.models import CallSession
    from sqlalchemy import select

    session_id = await _create_session(seeded_db, with_turns=None)

    with patch("app.summarizer.AsyncOpenAI") as mock_openai_cls:
        mock_client = AsyncMock()
        mock_openai_cls.return_value = mock_client

        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

        # OpenAI should NOT have been called
        mock_client.chat.completions.create.assert_not_called()

    # Summary should remain null
    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(CallSession).where(CallSession.id == session_id)
        )
        cs = result.scalar_one()
        assert cs.summary is None


async def test_summarizer_skips_silently_no_exception(seeded_db):
    """generate_summary_and_facts() with 0 turns → does NOT raise any exception."""
    from app.summarizer import generate_summary_and_facts

    session_id = await _create_session(seeded_db, with_turns=None)

    # Should not raise
    with patch("app.summarizer.AsyncOpenAI"):
        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(
                session_id, db
            )  # no assertion needed, just no raise


# ---------------------------------------------------------------------------
# CAP-4: GPT failure → logged, no exception raised
# ---------------------------------------------------------------------------


async def test_summarizer_gpt_failure_no_exception(seeded_db):
    """GPT failure → logged, generate_summary_and_facts() does not raise."""
    from app.summarizer import generate_summary_and_facts

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("user", "Hola, me interesa un seguro"),
            ("agent", "Perfecto, te cuento..."),
        ],
    )

    with patch("app.summarizer.AsyncOpenAI") as mock_openai_cls:
        mock_client = AsyncMock()
        mock_openai_cls.return_value = mock_client
        # Simulate API failure
        mock_client.chat.completions.create.side_effect = Exception("API timeout")

        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            # Must not raise
            await generate_summary_and_facts(session_id, db)


async def test_summarizer_gpt_failure_session_stays_completed(seeded_db):
    """GPT failure → session status stays 'completed' (no rollback of session status)."""
    from app.summarizer import generate_summary_and_facts
    from app.calls.models import CallSession
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[("user", "Necesito un seguro")],
    )

    with patch("app.summarizer.AsyncOpenAI") as mock_openai_cls:
        mock_client = AsyncMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = Exception("Network error")

        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    # Session should still be completed
    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(CallSession).where(CallSession.id == session_id)
        )
        cs = result.scalar_one()
        assert cs.status == "completed"


# ---------------------------------------------------------------------------
# CAP-4: do_not_call flag
# ---------------------------------------------------------------------------


async def test_summarizer_sets_do_not_call_flag(seeded_db):
    """When next_action_suggested='do_not_call' → Lead.do_not_call is set to True."""
    from app.summarizer import generate_summary_and_facts
    from app.leads.models import Lead
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "Hola, le llamo de Quintana Seguros"),
            ("user", "No me llamen más por favor"),
        ],
    )

    gpt_payload = {
        "summary": "El lead pidió no ser contactado más.",
        "objections": ["no quiere ser contactado"],
        "interest_level": 0,
        "current_insurance": None,
        "next_action_suggested": "do_not_call",
        "misc_facts": {},
    }

    with patch("app.summarizer.AsyncOpenAI") as mock_openai_cls:
        mock_client = AsyncMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_openai_response(
            gpt_payload
        )

        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    # Verify Lead.do_not_call is True
    async with seeded_db.async_session_factory() as db:
        result = await db.execute(select(Lead).where(Lead.id == "test-lead-sum-001"))
        lead = result.scalar_one()
        assert lead.do_not_call is True


async def test_summarizer_does_not_set_do_not_call_for_other_actions(seeded_db):
    """next_action_suggested='call_again' → Lead.do_not_call stays False."""
    from app.summarizer import generate_summary_and_facts
    from app.leads.models import Lead
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "Hola, le llamo de Quintana Seguros"),
            ("user", "Me interesa, llámeme la semana que viene"),
        ],
    )

    gpt_payload = {
        "summary": "Lead interesado, prefiere ser contactado la próxima semana.",
        "objections": [],
        "interest_level": 70,
        "current_insurance": None,
        "next_action_suggested": "call_again",
        "misc_facts": {},
    }

    with patch("app.summarizer.AsyncOpenAI") as mock_openai_cls:
        mock_client = AsyncMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_openai_response(
            gpt_payload
        )

        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(select(Lead).where(Lead.id == "test-lead-sum-001"))
        lead = result.scalar_one()
        assert lead.do_not_call is False


async def test_summarizer_persists_summary_and_facts(seeded_db):
    """Successful GPT call → summary + extracted_facts persisted to CallSession."""
    from app.summarizer import generate_summary_and_facts
    from app.calls.models import CallSession
    from sqlalchemy import select

    session_id = await _create_session(
        seeded_db,
        with_turns=[
            ("agent", "Hola"),
            ("user", "Sí, quiero cotizar"),
        ],
    )

    gpt_payload = {
        "summary": "Lead interesado en cotización.",
        "objections": [],
        "interest_level": 80,
        "current_insurance": "MAPFRE",
        "next_action_suggested": "send_quote",
        "misc_facts": {},
    }

    with patch("app.summarizer.AsyncOpenAI") as mock_openai_cls:
        mock_client = AsyncMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_openai_response(
            gpt_payload
        )

        assert seeded_db.async_session_factory is not None
        async with seeded_db.async_session_factory() as db:
            await generate_summary_and_facts(session_id, db)
            await db.commit()

    async with seeded_db.async_session_factory() as db:
        result = await db.execute(
            select(CallSession).where(CallSession.id == session_id)
        )
        cs = result.scalar_one()
        assert cs.summary == "Lead interesado en cotización."
        assert cs.extracted_facts is not None
        assert cs.extracted_facts["interest_level"] == 80
