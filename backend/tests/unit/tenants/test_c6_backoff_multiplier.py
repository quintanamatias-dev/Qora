"""Phase C6 — Retry & Recontact Policy: Client.scheduler_backoff_multiplier tests.

Spec:
- Client model has scheduler_backoff_multiplier with default 1.0.
- Schemas expose scheduler_backoff_multiplier (ClientCreate, ClientUpdate, ClientResponse).
- NextActionContext has telephony_status: str | None field.
"""

from __future__ import annotations

import pytest


# ===========================================================================
# Task 1.1 / 1.2: Client.scheduler_backoff_multiplier
# ===========================================================================


class TestClientBackoffMultiplierModel:
    """Client model must have scheduler_backoff_multiplier: float, default 1.0."""

    def test_scheduler_backoff_multiplier_attribute_exists(self):
        """Client model has scheduler_backoff_multiplier attribute."""
        from app.tenants.models import Client

        # The column must exist on the model's mapper
        from sqlalchemy import inspect

        mapper = inspect(Client)
        col_names = [c.key for c in mapper.mapper.columns]
        assert "scheduler_backoff_multiplier" in col_names, (
            "Client model must have scheduler_backoff_multiplier column"
        )

    def test_scheduler_backoff_multiplier_column_default_is_1_0(self):
        """Client model column default for scheduler_backoff_multiplier is 1.0."""
        from app.tenants.models import Client
        from sqlalchemy import inspect

        mapper = inspect(Client)
        col = mapper.mapper.columns["scheduler_backoff_multiplier"]
        # SQLAlchemy mapped_column(default=1.0) stores the default in col.default.arg
        assert col.default is not None, "Column must have a default defined"
        assert col.default.arg == 1.0, (
            f"Default must be 1.0, got {col.default.arg}"
        )

    def test_scheduler_backoff_multiplier_is_float_type(self):
        """scheduler_backoff_multiplier column is mapped as Float."""
        from app.tenants.models import Client
        from sqlalchemy import inspect, Float

        mapper = inspect(Client)
        col = mapper.mapper.columns["scheduler_backoff_multiplier"]
        assert isinstance(col.type, Float), (
            "scheduler_backoff_multiplier must be mapped as Float"
        )


# ===========================================================================
# Task 1.4: schemas expose scheduler_backoff_multiplier
# ===========================================================================

class TestClientSchemasBackoffMultiplier:
    """Client model must expose scheduler_backoff_multiplier for create/update/response.

    scheduler_backoff_multiplier belongs on Client (tenant), not on Agent.
    This unit-layer test confirms the model attribute is accessible;
    full schema-field coverage (ClientCreate/ClientUpdate/ClientResponse) is
    exercised in tests/unit/clients/test_c6_backoff_multiplier_validation.py.
    """

    def test_backoff_multiplier_exposed_in_tenant_create_response(self):
        """Client model attribute scheduler_backoff_multiplier is readable and settable."""
        from app.tenants.models import Client

        client = Client(
            id="test-client",
            name="Test Client",
            voice_id="v-123",
            scheduler_backoff_multiplier=1.5,
        )
        assert client.scheduler_backoff_multiplier == 1.5


# ===========================================================================
# Task 1.6 / 1.7: NextActionContext has telephony_status field
# ===========================================================================


class TestNextActionContextTelephonyStatus:
    """NextActionContext must have telephony_status: str | None = None."""

    def test_telephony_status_field_exists_with_none_default(self):
        """NextActionContext has telephony_status field defaulting to None."""
        from app.analysis.universal.next_action import NextActionContext

        import inspect as python_inspect

        sig = python_inspect.signature(NextActionContext.__init__)
        assert "telephony_status" in sig.parameters, (
            "NextActionContext must have telephony_status parameter"
        )
        param = sig.parameters["telephony_status"]
        assert param.default is None, (
            "telephony_status must default to None"
        )

    def test_telephony_status_accepts_string_value(self):
        """NextActionContext accepts telephony_status='voicemail'."""
        from app.analysis.universal.next_action import (
            NextActionContext,
            LeadSnapshot,
            ClientRules,
        )
        from app.analysis.universal.outcome import CallOutcome
        from app.analysis.universal.commitments import CommitmentsAxis
        from app.analysis.universal.objections import ObjectionsAxis
        from app.analysis.universal.problem import ProblemAxis
        from datetime import datetime, timezone

        ctx = NextActionContext(
            outcome=CallOutcome(
                classification="no_answer",
                reason="test",
                confidence="high",
            ),
            interest_level=50,
            commitments=CommitmentsAxis(),
            objections=ObjectionsAxis(),
            problem=ProblemAxis(pain_points=[]),
            lead=LeadSnapshot(
                call_count=1,
                do_not_call=False,
                last_called_at=datetime.now(timezone.utc),
            ),
            client=ClientRules(
                max_attempts=5,
                min_interest_for_followup=40,
                close_on_hard_rejection=True,
                scheduler_cooldown_minutes=60,
                scheduler_allowed_hours_start=9,
                scheduler_allowed_hours_end=20,
                scheduler_timezone="America/Argentina/Buenos_Aires",
            ),
            telephony_status="voicemail",
        )
        assert ctx.telephony_status == "voicemail"

    def test_telephony_status_defaults_to_none(self):
        """NextActionContext instantiated without telephony_status → None."""
        from app.analysis.universal.next_action import (
            NextActionContext,
            LeadSnapshot,
            ClientRules,
        )
        from app.analysis.universal.outcome import CallOutcome
        from app.analysis.universal.commitments import CommitmentsAxis
        from app.analysis.universal.objections import ObjectionsAxis
        from app.analysis.universal.problem import ProblemAxis
        from datetime import datetime, timezone

        ctx = NextActionContext(
            outcome=CallOutcome(
                classification="completed_positive",
                reason="test",
                confidence="high",
            ),
            interest_level=70,
            commitments=CommitmentsAxis(),
            objections=ObjectionsAxis(),
            problem=ProblemAxis(pain_points=[]),
            lead=LeadSnapshot(
                call_count=1,
                do_not_call=False,
                last_called_at=datetime.now(timezone.utc),
            ),
            client=ClientRules(
                max_attempts=5,
                min_interest_for_followup=40,
                close_on_hard_rejection=True,
                scheduler_cooldown_minutes=60,
                scheduler_allowed_hours_start=9,
                scheduler_allowed_hours_end=20,
                scheduler_timezone="America/Argentina/Buenos_Aires",
            ),
        )
        assert ctx.telephony_status is None
