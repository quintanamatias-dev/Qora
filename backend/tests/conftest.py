"""Pytest configuration and shared fixtures for QORA backend tests.

Provides:
- Async SQLite engine (isolated per test)
- App factory with QORA lifespan
- QORA Settings fixture (no Twilio dependencies)
- respx mocks for OpenAI/ElevenLabs
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Session store isolation — VSC-8 Fix A
# ---------------------------------------------------------------------------
# The module-level session_store singleton is shared across all tests in a process.
# Without cleanup between tests, find_by_client_lead() can find leftover sessions
# from earlier tests and skip creating new DB sessions — breaking tests that expect
# a new CallSession to be created on every request.
#
# This autouse fixture clears the singleton before every test automatically.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_session_store_between_tests():
    """Clear the global session_store before each test to prevent state leakage."""
    from app.voice.session import session_store

    session_store._sessions.clear()
    yield
    session_store._sessions.clear()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@pytest.fixture
def test_settings(tmp_path: Path):
    """Create QORA Settings pointing at an isolated SQLite file."""
    from app.core.config import Settings

    db_url = f"sqlite+aiosqlite:///{tmp_path}/qora_test.db"
    return Settings(
        openai_api_key=SecretStr("sk-test-openai"),
        elevenlabs_api_key=SecretStr("el-test-key"),
        database_url=db_url,
        debug=False,
    )


# ---------------------------------------------------------------------------
# Database engine
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_engine(test_settings):
    """Async SQLite engine with all QORA tables created. Torn down after test."""
    from app.core import database as db_module

    await db_module.init_db(test_settings)
    yield db_module
    await db_module.close_db()


@pytest_asyncio.fixture
async def db_session(test_settings, db_engine):
    """Yield a single async session for a test. Auto-commits on success."""
    assert db_engine.async_session_factory is not None, "DB not initialized"
    async with db_engine.async_session_factory() as session:
        yield session


# ---------------------------------------------------------------------------
# OpenAI streaming mock (SSE)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_openai_stream():
    """Return a factory for fake OpenAI SSE chunks."""

    def make_stream(tokens: list[str]):
        """Yield fake SSE chunk objects for each token."""

        async def _gen():
            for token in tokens:
                chunk = MagicMock()
                chunk.choices = [MagicMock()]
                chunk.choices[0].delta.content = token
                chunk.choices[0].delta.tool_calls = None
                chunk.choices[0].finish_reason = None
                yield chunk
            # Final chunk with finish_reason
            done_chunk = MagicMock()
            done_chunk.choices = [MagicMock()]
            done_chunk.choices[0].delta.content = None
            done_chunk.choices[0].delta.tool_calls = None
            done_chunk.choices[0].finish_reason = "stop"
            yield done_chunk

        return _gen()

    return make_stream
