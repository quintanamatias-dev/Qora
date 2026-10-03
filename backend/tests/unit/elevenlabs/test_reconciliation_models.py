"""Unit tests for ElevenLabsReconciliationReport model fields.

Spec: openspec/changes/elevenlabs-reconciler/design.md — Interfaces/Contracts.
"""

from __future__ import annotations

from sqlalchemy import UniqueConstraint


def test_reconciliation_report_model_fields_exist():
    from app.elevenlabs.models import ElevenLabsReconciliationReport

    columns = ElevenLabsReconciliationReport.__table__.columns
    expected_fields = {
        "id",
        "agent_id",
        "client_id",
        "status",
        "drift_fields",
        "status_reason",
        "checked_at",
    }
    assert expected_fields.issubset(set(columns.keys()))


def test_reconciliation_report_model_has_unique_agent_id_constraint():
    from app.elevenlabs.models import ElevenLabsReconciliationReport

    unique_constraints = [
        c
        for c in ElevenLabsReconciliationReport.__table__.constraints
        if isinstance(c, UniqueConstraint)
    ]
    assert any(
        [col.name for col in uc.columns] == ["agent_id"] for uc in unique_constraints
    )
