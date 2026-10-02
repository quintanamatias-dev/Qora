"""Phase 1 (agent-config-revisions-routing) — AgentConfigRevision model.

Covers task 1.1: AgentConfigRevision model fields + Agent.active_revision_id.
"""

from __future__ import annotations

from app.core.database import Base


def test_agent_config_revision_model_fields_exist():
    """AgentConfigRevision exists with the fields design.md D4 requires."""
    from app.tenants.models import AgentConfigRevision

    table = AgentConfigRevision.__table__
    assert table.name == "agent_config_revisions"

    columns = {c.name: c for c in table.columns}
    expected = {
        "id",
        "agent_id",
        "revision_number",
        "config",
        "schema_version",
        "source",
        "created_by",
        "created_at",
        "note",
    }
    assert expected.issubset(columns), f"Missing columns: {expected - set(columns)}"

    assert columns["agent_id"].foreign_keys, "agent_id must be a FK to agents.id"
    fk_targets = {str(fk.column) for fk in columns["agent_id"].foreign_keys}
    assert "agents.id" in fk_targets


def test_agent_has_active_revision_id_column():
    """Agent gains an active_revision_id FK column pointing at agent_config_revisions."""
    from app.tenants.models import Agent

    columns = {c.name: c for c in Agent.__table__.columns}
    assert "active_revision_id" in columns
    assert columns["active_revision_id"].nullable is True

    fk_targets = {str(fk.column) for fk in columns["active_revision_id"].foreign_keys}
    assert "agent_config_revisions.id" in fk_targets


def test_agent_config_revision_registered_on_base_metadata():
    """Importing the model registers it on Base.metadata (used by Alembic autogenerate checks)."""
    from app.tenants import models  # noqa: F401

    assert "agent_config_revisions" in Base.metadata.tables
