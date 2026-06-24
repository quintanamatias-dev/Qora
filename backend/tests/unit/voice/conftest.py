"""Shared fixtures for tests/unit/voice.

Provides:
- `_patch_custom_fields_get_all`: autouse fixture that stubs out
  `lead_custom_fields_service.get_all` with an empty-dict return so that
  unit tests passing a raw `AsyncMock()` as `db` do not produce
  RuntimeWarning about leaked unawaited coroutines.

  Background: `get_all` calls `await db.execute(stmt)` then
  `result.scalars().all()`.  When `db` is an `AsyncMock`, the call to
  `result.scalars()` (where `result` is itself an `AsyncMock`) returns a
  coroutine that is never awaited, triggering:
      RuntimeWarning: coroutine 'AsyncMockMixin._execute_mock_call' was never awaited

  Tests that need specific custom-field data (e.g.
  `test_build_voice_context_lead_profile_contains_lead_name`) supply their
  own explicit patch that takes precedence over this autouse stub.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def _patch_custom_fields_get_all():
    """Stub lead_custom_fields_service.get_all to return {} in all voice unit tests.

    Prevents AsyncMock coroutine leaks when `build_voice_context` is called
    with a raw `AsyncMock()` db session in tests that do not care about
    custom fields.  Tests that verify custom-field behavior supply their own
    patch which takes precedence because it is applied in a narrower scope.
    """
    with patch(
        "app.leads.lead_custom_fields_service.get_all",
        new_callable=AsyncMock,
        return_value={},
    ):
        yield
