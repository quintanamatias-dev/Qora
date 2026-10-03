"""Phase 1 (analysis-profiles) — Task 1.3: ClientAnalysisProfileRevision model.

Scope note: CallAnalysis.analysis_profile_revision_id is deferred to Phase 3
(per-call catalog injection) — out of this task's allowed edit surface
(backend/app/calls/models.py is not touched here).
"""

from __future__ import annotations

from app.core.database import Base


def test_client_analysis_profile_revision_model_fields_exist():
    from app.tenants.models import ClientAnalysisProfileRevision

    table = ClientAnalysisProfileRevision.__table__
    assert table.name == "client_analysis_profile_revisions"

    columns = {c.name: c for c in table.columns}
    expected = {
        "id",
        "client_id",
        "revision_number",
        "config",
        "source",
        "created_by",
        "created_at",
        "note",
    }
    assert expected.issubset(columns), f"Missing columns: {expected - set(columns)}"

    assert columns["client_id"].foreign_keys, "client_id must be a FK to clients.id"
    fk_targets = {str(fk.column) for fk in columns["client_id"].foreign_keys}
    assert "clients.id" in fk_targets

    unique_constraints = [
        c for c in table.constraints if c.__class__.__name__ == "UniqueConstraint"
    ]
    assert any(
        {col.name for col in uc.columns} == {"client_id", "revision_number"}
        for uc in unique_constraints
    ), "expected a unique(client_id, revision_number) constraint"


def test_client_has_active_analysis_profile_revision_fk():
    from app.tenants.models import Client

    columns = {c.name: c for c in Client.__table__.columns}
    assert "active_analysis_profile_revision_id" in columns
    assert columns["active_analysis_profile_revision_id"].nullable is True

    fk_targets = {
        str(fk.column) for fk in columns["active_analysis_profile_revision_id"].foreign_keys
    }
    assert "client_analysis_profile_revisions.id" in fk_targets


def test_client_analysis_profile_revision_registered_on_base_metadata():
    from app.tenants import models  # noqa: F401

    assert "client_analysis_profile_revisions" in Base.metadata.tables
