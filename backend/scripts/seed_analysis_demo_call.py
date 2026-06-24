"""Seed one isolated real persisted Analysis demo call from a synthetic transcript.

This is intentionally different from ``smoke_test_analysis.py``:
- smoke_test_analysis validates GPT outputs without touching the DB;
- this script creates a real Lead + CallSession + TranscriptTurn rows, then runs
  the current production summarizer so the dashboard sees the same data shape a
  customer would see after a real call.

Usage:
    cd backend && python scripts/seed_analysis_demo_call.py

Optional:
    cd backend && python scripts/seed_analysis_demo_call.py --scenario negative
"""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import delete, select

# Add backend to path so imports work when run from the repo root or backend/.
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
# B8: Load from repo-root/.env (single source of truth).
# Path resolution: BACKEND_DIR is backend/ → .parent is repo-root/
load_dotenv(BACKEND_DIR.parent / ".env")

from smoke_test_analysis import TRANSCRIPT_NEGATIVE, TRANSCRIPT_POSITIVE  # noqa: E402


CLIENT_ID = "quintana-seguros"


def _today_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _parse_transcript(transcript: str) -> list[tuple[str, str]]:
    """Convert ``Agente:``/``Lead:`` transcript lines into DB roles."""
    turns: list[tuple[str, str]] = []
    for raw_line in transcript.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("Agente:"):
            turns.append(("agent", line.removeprefix("Agente:").strip()))
        elif line.startswith("Lead:"):
            turns.append(("user", line.removeprefix("Lead:").strip()))
    return turns


async def _delete_existing_demo_rows(session, *, lead_id: str, call_id: str) -> None:
    """Keep reruns isolated: one lead, one call, today's date."""
    from app.calls.models import CallAnalysis, CallSession, TranscriptTurn
    from app.leads.models import Lead, LeadInterestHistory, LeadProfileFact

    await session.execute(
        delete(CallAnalysis).where(CallAnalysis.session_id == call_id)
    )
    await session.execute(
        delete(TranscriptTurn).where(TranscriptTurn.session_id == call_id)
    )
    await session.execute(delete(CallSession).where(CallSession.id == call_id))
    await session.execute(
        delete(LeadInterestHistory).where(LeadInterestHistory.lead_id == lead_id)
    )
    await session.execute(
        delete(LeadProfileFact).where(LeadProfileFact.lead_id == lead_id)
    )
    await session.execute(delete(Lead).where(Lead.id == lead_id))


async def seed_demo_call(scenario: str) -> None:
    from app.calls.models import TranscriptTurn
    from app.calls.service import create_session
    from app.core import database as db_module
    from app.core.config import Settings
    from app.leads.models import Lead, LeadStatus
    from app.summarizer import generate_summary_and_facts
    from app.tenants.service import get_default_agent, seed_quintana
    from scripts.migrate import run_migrations

    transcript = TRANSCRIPT_POSITIVE if scenario == "positive" else TRANSCRIPT_NEGATIVE
    turns = _parse_transcript(transcript)
    if not turns:
        raise RuntimeError("Synthetic transcript did not produce any turns")

    # Ensure schema exists before opening a session.
    # init_db() no longer calls create_all() (PR2 cutover); migrations must run first.
    run_migrations()

    settings = Settings()
    await db_module.init_db(settings)

    today = datetime.now(timezone.utc)
    stamp = _today_stamp()
    lead_id = f"analysis-demo-{scenario}-{stamp}"
    call_id = f"analysis-demo-call-{scenario}-{stamp}"
    conversation_id = f"synthetic-analysis-{scenario}-{stamp}"

    assert db_module.async_session_factory is not None
    async with db_module.async_session_factory() as session:
        await seed_quintana(session)
        agent = await get_default_agent(session, CLIENT_ID)
        if agent is None:
            raise RuntimeError(f"No default agent found for client {CLIENT_ID!r}")

        await _delete_existing_demo_rows(session, lead_id=lead_id, call_id=call_id)

        if scenario == "positive":
            lead = Lead(
                id=lead_id,
                client_id=CLIENT_ID,
                name=f"Analysis Demo Martín {stamp}",
                phone=f"+5491100{stamp[-4:]}",
                email=None,
                car_make="Toyota",
                car_model="Corolla",  # intentionally stale; transcript corrects it
                car_year=2022,  # intentionally stale; transcript corrects it
                current_insurance="La Caja",
                status=LeadStatus.NEW.value,
                call_count=0,
                created_at=today,
                updated_at=today,
            )
        else:
            lead = Lead(
                id=lead_id,
                client_id=CLIENT_ID,
                name=f"Analysis Demo Ricardo {stamp}",
                phone=f"+5491199{stamp[-4:]}",
                current_insurance=None,
                status=LeadStatus.NEW.value,
                call_count=0,
                created_at=today,
                updated_at=today,
            )

        session.add(lead)
        await session.flush()

        call = await create_session(
            session,
            client_id=CLIENT_ID,
            lead_id=lead.id,
            elevenlabs_conversation_id=conversation_id,
            session_id=call_id,
            agent_id=agent.id,
        )

        started_at = today.replace(hour=14, minute=30, second=0, microsecond=0)
        ended_at = started_at + timedelta(seconds=max(60, len(turns) * 8))
        call.started_at = started_at
        call.ended_at = ended_at
        call.status = "completed"
        call.outcome = "completed"
        call.closed_reason = "synthetic_analysis_demo"
        call.duration_seconds = (ended_at - started_at).total_seconds()
        call.billable_minutes = math.ceil(call.duration_seconds / 60)

        for index, (role, content) in enumerate(turns):
            session.add(
                TranscriptTurn(
                    id=str(uuid.uuid4()),
                    session_id=call.id,
                    role=role,
                    content=content,
                    timestamp=started_at + timedelta(seconds=index * 8),
                )
            )

        lead.call_count = 1
        lead.last_called_at = ended_at
        lead.status = LeadStatus.CALLED.value
        call.total_agent_turns = sum(1 for role, _ in turns if role == "agent")
        call.total_user_turns = sum(1 for role, _ in turns if role == "user")

        await session.flush()

        # Run the production persistence path: CallSession + CallAnalysis + Lead merge.
        await generate_summary_and_facts(call.id, session)
        await session.commit()

        analysis_result = await session.execute(
            select(Lead.interest_level, Lead.next_action, Lead.do_not_call).where(
                Lead.id == lead.id
            )
        )
        interest_level, next_action, do_not_call = analysis_result.one()

    await db_module.close_db()

    print("✅ Seeded isolated Analysis demo call")
    print(f"   scenario: {scenario}")
    print(f"   date: {today.date().isoformat()}")
    print(f"   client_id: {CLIENT_ID}")
    print(f"   agent_id: {agent.id}")
    print(f"   lead_id: {lead_id}")
    print(f"   call_session_id: {call_id}")
    print(f"   interest_level: {interest_level}")
    print(f"   next_action: {next_action}")
    print(f"   do_not_call: {do_not_call}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scenario",
        choices=("positive", "negative"),
        default="positive",
        help="Synthetic smoke transcript to persist as a real call.",
    )
    args = parser.parse_args()
    asyncio.run(seed_demo_call(args.scenario))


if __name__ == "__main__":
    main()
