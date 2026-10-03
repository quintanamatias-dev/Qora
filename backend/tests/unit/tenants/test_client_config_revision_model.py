"""Phase 3 (agent-config-inheritance) — Task 3.1: ClientConfigRevision model.

Covers: ClientConfigRevision model fields + Client.active_config_revision_id.
"""

from __future__ import annotations

from app.core.database import Base


def test_client_config_revision_model_fields_exist():
    """ClientConfigRevision exists with the fields design.md D11 requires."""
    from app.tenants.models import ClientConfigRevision

    table = ClientConfigRevision.__table__
    assert table.name == "client_config_revisions"

    columns = {c.name: c for c in table.columns}
    expected = {
        "id",
        "client_id",
        "revision_number",
        "config",
        "schema_version",
        "source",
        "created_by",
        "created_at",
        "note",
    }
    assert expected.issubset(columns), f"Missing columns: {expected - set(columns)}"

    assert columns["client_id"].foreign_keys, "client_id must be a FK to clients.id"
    fk_targets = {str(fk.column) for fk in columns["client_id"].foreign_keys}
    assert "clients.id" in fk_targets


def test_client_has_active_config_revision_id_column():
    """Client gains an active_config_revision_id FK column pointing at client_config_revisions."""
    from app.tenants.models import Client

    columns = {c.name: c for c in Client.__table__.columns}
    assert "active_config_revision_id" in columns
    assert columns["active_config_revision_id"].nullable is True

    fk_targets = {
        str(fk.column) for fk in columns["active_config_revision_id"].foreign_keys
    }
    assert "client_config_revisions.id" in fk_targets


def test_client_config_revision_registered_on_base_metadata():
    """Importing the model registers it on Base.metadata (used by Alembic autogenerate checks)."""
    from app.tenants import models  # noqa: F401

    assert "client_config_revisions" in Base.metadata.tables
