"""Unit and integration tests for WU2 — CallSession SIP observability schema.

Spec: call-sip-observability — Requirement: CallSession Schema — Nullable Observability Columns

Tasks:
  2.1 — CallSession model has 5 new nullable columns
  2.2 — Alembic migration adds the columns using batch alter (SQLite-safe)
  2.3 — Migration integration: existing rows remain unchanged; new fields default NULL;
          downgrade is safe

TDD: Tests written BEFORE implementation.
All migration tests use the shared db_engine fixture (Alembic upgrade head).
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Task 2.1 — ORM model structure tests (no DB needed)
# ---------------------------------------------------------------------------


class TestCallSessionOrmColumns:
    """Verify CallSession ORM has the 5 new SIP observability columns."""

    def test_sip_call_id_column_exists(self):
        """CallSession must have sip_call_id as nullable String column.

        GIVEN the CallSession ORM model
        WHEN inspecting its mapped columns
        THEN sip_call_id is present and nullable.
        """
        from app.calls.models import CallSession
        from sqlalchemy import inspect

        mapper = inspect(CallSession)
        col_names = {c.key for c in mapper.columns}
        assert "sip_call_id" in col_names, (
            "CallSession.sip_call_id column is missing from ORM model"
        )

    def test_sip_status_code_column_exists(self):
        """CallSession must have sip_status_code as nullable Integer column."""
        from app.calls.models import CallSession
        from sqlalchemy import inspect

        mapper = inspect(CallSession)
        col_names = {c.key for c in mapper.columns}
        assert "sip_status_code" in col_names, (
            "CallSession.sip_status_code column is missing from ORM model"
        )

    def test_sip_reason_column_exists(self):
        """CallSession must have sip_reason as nullable String column."""
        from app.calls.models import CallSession
        from sqlalchemy import inspect

        mapper = inspect(CallSession)
        col_names = {c.key for c in mapper.columns}
        assert "sip_reason" in col_names, (
            "CallSession.sip_reason column is missing from ORM model"
        )

    def test_reconciled_at_column_exists(self):
        """CallSession must have reconciled_at as nullable DateTime column."""
        from app.calls.models import CallSession
        from sqlalchemy import inspect

        mapper = inspect(CallSession)
        col_names = {c.key for c in mapper.columns}
        assert "reconciled_at" in col_names, (
            "CallSession.reconciled_at column is missing from ORM model"
        )

    def test_reconciliation_source_column_exists(self):
        """CallSession must have reconciliation_source as nullable String column."""
        from app.calls.models import CallSession
        from sqlalchemy import inspect

        mapper = inspect(CallSession)
        col_names = {c.key for c in mapper.columns}
        assert "reconciliation_source" in col_names, (
            "CallSession.reconciliation_source column is missing from ORM model"
        )

    def test_all_five_sip_columns_are_nullable(self):
        """All five SIP observability columns must be nullable.

        Spec: All columns are nullable — existing rows unaffected (NULL on read).
        """
        from app.calls.models import CallSession
        from sqlalchemy import inspect

        mapper = inspect(CallSession)
        sip_cols = {
            "sip_call_id", "sip_status_code", "sip_reason",
            "reconciled_at", "reconciliation_source"
        }
        # mapper.columns yields sqlalchemy.orm.properties.ColumnProperty objects.
        # Each has .key and .columns (the mapped SA Column objects).
        for prop in mapper.column_attrs:
            if prop.key in sip_cols:
                sa_col = prop.columns[0]
                assert sa_col.nullable, (
                    f"CallSession.{prop.key} must be nullable "
                    f"(backward-compatible — existing rows must not be affected)"
                )


# ---------------------------------------------------------------------------
# Task 2.3 — Migration integration tests (uses db_engine fixture)
# ---------------------------------------------------------------------------


class TestSipMigrationApplies:
    """Migration applies cleanly and new columns are NULL on existing rows."""

    @pytest.mark.asyncio
    async def test_migration_adds_sip_columns_to_call_sessions(self, db_session):
        """GIVEN an Alembic-migrated test DB
        WHEN the schema is inspected
        THEN the five SIP observability columns exist on call_sessions.

        Spec: Scenario: Migration applies without data loss.
        """
        from sqlalchemy import text

        result = await db_session.execute(text("PRAGMA table_info(call_sessions)"))
        columns = {row[1] for row in result.fetchall()}

        assert "sip_call_id" in columns, "sip_call_id column missing after migration"
        assert "sip_status_code" in columns, "sip_status_code column missing after migration"
        assert "sip_reason" in columns, "sip_reason column missing after migration"
        assert "reconciled_at" in columns, "reconciled_at column missing after migration"
        assert "reconciliation_source" in columns, "reconciliation_source column missing after migration"

    @pytest.mark.asyncio
    async def test_new_call_session_has_null_sip_fields(self, db_session):
        """GIVEN a new CallSession created after migration
        WHEN it is committed and read back
        THEN all five SIP fields are NULL.

        Spec: Scenario: SIP observability columns present at creation — NULL.
        """
        import uuid
        from app.calls.models import CallSession

        session_id = str(uuid.uuid4())
        cs = CallSession(
            id=session_id,
            client_id="test-client",
            lead_id=None,
            status="initiated",
            started_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(cs)
        await db_session.commit()
        await db_session.refresh(cs)

        assert cs.sip_call_id is None, "sip_call_id must default to NULL"
        assert cs.sip_status_code is None, "sip_status_code must default to NULL"
        assert cs.sip_reason is None, "sip_reason must default to NULL"
        assert cs.reconciled_at is None, "reconciled_at must default to NULL"
        assert cs.reconciliation_source is None, "reconciliation_source must default to NULL"

    @pytest.mark.asyncio
    async def test_sip_fields_can_be_written_and_read_back(self, db_session):
        """GIVEN a CallSession with SIP fields populated
        WHEN committed and read back
        THEN all SIP field values are preserved exactly.
        """
        import uuid
        from app.calls.models import CallSession

        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).replace(microsecond=0)
        cs = CallSession(
            id=session_id,
            client_id="test-client",
            status="initiated",
            started_at=now,
            created_at=now,
            sip_call_id="otb_abc123xyz",
            sip_status_code=487,
            sip_reason="Request Terminated",
            reconciled_at=now,
            reconciliation_source="probe",
        )
        db_session.add(cs)
        await db_session.commit()
        await db_session.refresh(cs)

        assert cs.sip_call_id == "otb_abc123xyz"
        assert cs.sip_status_code == 487
        assert cs.sip_reason == "Request Terminated"
        assert cs.reconciliation_source == "probe"
        assert cs.reconciled_at is not None

    @pytest.mark.asyncio
    async def test_existing_session_sip_fields_remain_null_after_migration(self, db_session):
        """GIVEN a session created before the SIP observability migration (simulated)
        WHEN the session is read after migration
        THEN SIP fields are NULL (no data loss to pre-migration rows).

        Spec: Scenario: Migration applies without data loss.
        Note: Since we can't literally run migration on old DB in unit test, we
        verify that a session with no SIP data set has NULL SIP fields —
        confirming the nullable default doesn't corrupt anything.
        """
        import uuid
        from app.calls.models import CallSession

        session_id = str(uuid.uuid4())
        cs = CallSession(
            id=session_id,
            client_id="test-client",
            status="completed",
            started_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            # No SIP fields set — simulates pre-migration row
        )
        db_session.add(cs)
        await db_session.commit()
        await db_session.refresh(cs)

        # Pre-migration rows must read NULL for all SIP columns
        assert cs.sip_call_id is None
        assert cs.sip_status_code is None
        assert cs.sip_reason is None
        assert cs.reconciled_at is None
        assert cs.reconciliation_source is None

        # And none of the pre-existing columns are affected
        assert cs.status == "completed"
        assert cs.client_id == "test-client"
