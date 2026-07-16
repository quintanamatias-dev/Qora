"""Phase C6 pre-commit remediation — Warning W1: scheduler_backoff_multiplier validation.

Spec requirement: The system MUST validate scheduler_backoff_multiplier server-side
to prevent zero/negative/NaN/infinite/huge values from producing immediate or
excessive retries.

Valid range: finite, >= 1.0, <= 10.0
  - 1.0 = flat delay (preserves existing behaviour)
  - 10.0 = max sane escalation (10× base cooldown at higher attempts)

Covers:
- ClientCreate: rejects invalid values, accepts valid range [1.0, 10.0]
- ClientUpdate: rejects invalid values, accepts None (field not updated)
- ClientResponse: exposes scheduler_backoff_multiplier with correct default
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Helper: ClientCreate validator tests
# ---------------------------------------------------------------------------


class TestBackoffMultiplierValidation:
    """ClientCreate and ClientUpdate must reject invalid backoff multiplier values."""

    # --- Invalid values that must be rejected ---

    def test_zero_multiplier_rejected_in_create(self):
        """multiplier=0 → immediate retry on every attempt, must be rejected."""
        from app.clients.schemas import ClientCreate

        with pytest.raises(ValidationError, match="scheduler_backoff_multiplier"):
            ClientCreate(name="Test Client", scheduler_backoff_multiplier=0.0)

    def test_below_one_multiplier_rejected_in_create(self):
        """multiplier=0.9 < 1.0 → delay shrinks per attempt, must be rejected."""
        from app.clients.schemas import ClientCreate

        with pytest.raises(ValidationError, match="scheduler_backoff_multiplier"):
            ClientCreate(name="Test Client", scheduler_backoff_multiplier=0.9)

    def test_negative_multiplier_rejected_in_create(self):
        """multiplier=-1.0 → negative delay, must be rejected."""
        from app.clients.schemas import ClientCreate

        with pytest.raises(ValidationError, match="scheduler_backoff_multiplier"):
            ClientCreate(name="Test Client", scheduler_backoff_multiplier=-1.0)

    def test_above_max_multiplier_rejected_in_create(self):
        """multiplier=11.0 > 10.0 → excessive escalation, must be rejected."""
        from app.clients.schemas import ClientCreate

        with pytest.raises(ValidationError, match="scheduler_backoff_multiplier"):
            ClientCreate(name="Test Client", scheduler_backoff_multiplier=11.0)

    def test_infinity_multiplier_rejected_in_create(self):
        """multiplier=inf → infinite delay, must be rejected."""
        from app.clients.schemas import ClientCreate

        with pytest.raises(ValidationError, match="scheduler_backoff_multiplier"):
            ClientCreate(name="Test Client", scheduler_backoff_multiplier=float("inf"))

    def test_nan_multiplier_rejected_in_create(self):
        """multiplier=NaN → undefined behaviour, must be rejected."""
        from app.clients.schemas import ClientCreate

        with pytest.raises(ValidationError, match="scheduler_backoff_multiplier"):
            ClientCreate(name="Test Client", scheduler_backoff_multiplier=float("nan"))

    # --- Valid values that must be accepted ---

    def test_default_multiplier_accepted(self):
        """Default multiplier=1.0 must be valid (flat delay, existing behaviour)."""
        from app.clients.schemas import ClientCreate

        obj = ClientCreate(name="Test Client")
        assert obj.scheduler_backoff_multiplier == 1.0

    def test_exact_minimum_accepted(self):
        """multiplier=1.0 (lower bound) must be accepted."""
        from app.clients.schemas import ClientCreate

        obj = ClientCreate(name="Test Client", scheduler_backoff_multiplier=1.0)
        assert obj.scheduler_backoff_multiplier == 1.0

    def test_mid_range_multiplier_accepted(self):
        """multiplier=2.5 (within range) must be accepted."""
        from app.clients.schemas import ClientCreate

        obj = ClientCreate(name="Test Client", scheduler_backoff_multiplier=2.5)
        assert obj.scheduler_backoff_multiplier == 2.5

    def test_exact_maximum_accepted(self):
        """multiplier=10.0 (upper bound) must be accepted."""
        from app.clients.schemas import ClientCreate

        obj = ClientCreate(name="Test Client", scheduler_backoff_multiplier=10.0)
        assert obj.scheduler_backoff_multiplier == 10.0


class TestBackoffMultiplierUpdateValidation:
    """ClientUpdate must also reject invalid backoff multiplier values."""

    def test_zero_multiplier_rejected_in_update(self):
        """multiplier=0 must be rejected in ClientUpdate too."""
        from app.clients.schemas import ClientUpdate

        with pytest.raises(ValidationError, match="scheduler_backoff_multiplier"):
            ClientUpdate(scheduler_backoff_multiplier=0.0)

    def test_none_multiplier_accepted_in_update(self):
        """None is valid in ClientUpdate (field not being updated)."""
        from app.clients.schemas import ClientUpdate

        obj = ClientUpdate(scheduler_backoff_multiplier=None)
        assert obj.scheduler_backoff_multiplier is None

    def test_valid_multiplier_accepted_in_update(self):
        """multiplier=1.5 must be accepted in ClientUpdate."""
        from app.clients.schemas import ClientUpdate

        obj = ClientUpdate(scheduler_backoff_multiplier=1.5)
        assert obj.scheduler_backoff_multiplier == 1.5


class TestClientResponseBackoffMultiplier:
    """ClientResponse must expose scheduler_backoff_multiplier with the correct default."""

    def test_client_response_has_scheduler_backoff_multiplier_field(self):
        """ClientResponse.scheduler_backoff_multiplier defaults to 1.0."""
        from datetime import datetime, timezone
        from app.clients.schemas import ClientResponse

        resp = ClientResponse(
            client_id="test-client",
            name="Test",
            agent_name="Agent",
            voice_id="voice-001",
            is_active=True,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        assert resp.scheduler_backoff_multiplier == 1.0, (
            f"ClientResponse.scheduler_backoff_multiplier must default to 1.0, "
            f"got {resp.scheduler_backoff_multiplier!r}"
        )

    def test_client_response_serialises_custom_multiplier(self):
        """ClientResponse serialises a non-default scheduler_backoff_multiplier."""
        from datetime import datetime, timezone
        from app.clients.schemas import ClientResponse

        resp = ClientResponse(
            client_id="test-client",
            name="Test",
            agent_name="Agent",
            voice_id="voice-001",
            is_active=True,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            scheduler_backoff_multiplier=2.5,
        )
        assert resp.scheduler_backoff_multiplier == 2.5, (
            f"ClientResponse.scheduler_backoff_multiplier must carry the provided "
            f"value (2.5), got {resp.scheduler_backoff_multiplier!r}"
        )
