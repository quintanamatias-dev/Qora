"""Phase 3 (client-integrations-secrets) — Task 2.1: ClientIntegration + ClientSecret models.

Covers: model fields per design.md's Interfaces/Contracts section, and the
unique(client_id, provider) / unique(client_id, name) constraints.
"""

from __future__ import annotations

from app.core.database import Base


def test_client_integration_model_fields_exist():
    """ClientIntegration exists with the fields design.md requires."""
    from app.tenants.models import ClientIntegration

    table = ClientIntegration.__table__
    assert table.name == "client_integrations"

    columns = {c.name: c for c in table.columns}
    expected = {
        "id",
        "client_id",
        "provider",
        "enabled",
        "config",
        "status",
        "status_reason",
        "last_checked_at",
        "created_at",
        "created_by",
        "updated_at",
        "updated_by",
    }
    assert expected.issubset(columns), f"Missing columns: {expected - set(columns)}"

    assert columns["client_id"].foreign_keys, "client_id must be a FK to clients.id"
    fk_targets = {str(fk.column) for fk in columns["client_id"].foreign_keys}
    assert "clients.id" in fk_targets

    unique_constraints = [
        c for c in table.constraints if c.__class__.__name__ == "UniqueConstraint"
    ]
    unique_column_sets = {
        frozenset(col.name for col in uc.columns) for uc in unique_constraints
    }
    assert frozenset({"client_id", "provider"}) in unique_column_sets


def test_client_secret_model_fields_exist():
    """ClientSecret exists with the fields design.md requires."""
    from app.tenants.models import ClientSecret

    table = ClientSecret.__table__
    assert table.name == "client_secrets"

    columns = {c.name: c for c in table.columns}
    expected = {
        "id",
        "client_id",
        "integration_id",
        "name",
        "ciphertext",
        "key_id",
        "created_at",
        "created_by",
        "updated_at",
        "updated_by",
    }
    assert expected.issubset(columns), f"Missing columns: {expected - set(columns)}"

    assert columns["client_id"].foreign_keys, "client_id must be a FK to clients.id"
    fk_targets = {str(fk.column) for fk in columns["client_id"].foreign_keys}
    assert "clients.id" in fk_targets

    assert columns["integration_id"].nullable is True
    integration_fk_targets = {
        str(fk.column) for fk in columns["integration_id"].foreign_keys
    }
    assert "client_integrations.id" in integration_fk_targets

    unique_constraints = [
        c for c in table.constraints if c.__class__.__name__ == "UniqueConstraint"
    ]
    unique_column_sets = {
        frozenset(col.name for col in uc.columns) for uc in unique_constraints
    }
    assert frozenset({"client_id", "name"}) in unique_column_sets


def test_models_registered_on_base_metadata():
    """Importing the models registers them on Base.metadata (Alembic autogenerate)."""
    from app.tenants import models  # noqa: F401

    assert "client_integrations" in Base.metadata.tables
    assert "client_secrets" in Base.metadata.tables
