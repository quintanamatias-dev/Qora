"""close_session() must start summarization only after the caller commits.

The summarizer runs in its own DB session. When it started right after
close_session() flushed (before the caller's commit), it could not see the
turns merged in from sibling sessions, logged ``summarizer_skipped_no_turns``
and never wrote the lead's profile facts. Production outbound calls hit this
on every call whose turns landed on a sibling session.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.calls.models import CallSession


async def _create_open_session(db_module) -> str:
    async with db_module.async_session_factory() as sess:
        cs = CallSession(
            id=str(uuid.uuid4()),
            client_id="quintana-seguros",
            lead_id=None,
            elevenlabs_conversation_id=f"conv-{uuid.uuid4().hex[:8]}",
            status="initiated",
            started_at=datetime.now(timezone.utc) - timedelta(seconds=60),
        )
        sess.add(cs)
        await sess.commit()
        return cs.id


async def test_summarize_waits_for_commit(db_engine):
    from app.calls import service
    from app.core import database as db_module

    session_id = await _create_open_session(db_module)

    with (
        patch.object(service.settings, "enable_job_executor", False),
        patch.object(service, "_schedule_summarize") as schedule,
    ):
        async with db_module.async_session_factory() as sess:
            await service.close_session(sess, session_id=session_id, closed_reason="agent_ended")
            assert not schedule.called, "summarize started before the transaction committed"

            await sess.commit()
            schedule.assert_called_once_with(session_id)


async def test_summarize_never_starts_on_rollback(db_engine):
    from app.calls import service
    from app.core import database as db_module

    session_id = await _create_open_session(db_module)

    with (
        patch.object(service.settings, "enable_job_executor", False),
        patch.object(service, "_schedule_summarize") as schedule,
    ):
        async with db_module.async_session_factory() as sess:
            await service.close_session(sess, session_id=session_id, closed_reason="agent_ended")
            await sess.rollback()
            # Unrelated work committed later on the same session must not
            # summarize a close that was rolled back.
            await sess.commit()

        assert not schedule.called


async def test_voicemail_heuristic_counts_turns_merged_from_siblings(db_engine):
    """A short call whose user turns live on a sibling session is not voicemail.

    The heuristic flags calls under 30 s with zero user turns. It must run
    after sibling turns are merged, or every such call is mislabeled.
    """
    from app.calls import service
    from app.core import database as db_module

    now = datetime.now(timezone.utc)
    async with db_module.async_session_factory() as sess:
        primary = CallSession(
            id=str(uuid.uuid4()),
            client_id="quintana-seguros",
            lead_id=None,
            elevenlabs_conversation_id=f"conv-{uuid.uuid4().hex[:8]}",
            status="initiated",
            telephony_status="dialing",
            started_at=now - timedelta(seconds=20),
        )
        sibling = CallSession(
            id=str(uuid.uuid4()),
            client_id="quintana-seguros",
            lead_id=None,
            elevenlabs_conversation_id=None,
            status="initiated",
            started_at=now - timedelta(seconds=20),
        )
        sess.add_all([primary, sibling])
        await sess.flush()
        await service.add_transcript_turn(sess, sibling.id, "user", "Hola, si, soy yo")
        await sess.commit()
        primary_id = primary.id

    with (
        patch.object(service.settings, "enable_job_executor", False),
        patch.object(service, "_schedule_summarize"),
    ):
        async with db_module.async_session_factory() as sess:
            cs, _ = await service.close_session(sess, session_id=primary_id, closed_reason="agent_ended")
            await sess.commit()

    assert cs.total_user_turns == 1
    assert cs.telephony_status != "voicemail"
