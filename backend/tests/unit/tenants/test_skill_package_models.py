"""skill-packages (P4-D1) — Task 1.1: SkillPackage, Skill, SkillRevision models."""

from __future__ import annotations

from app.core.database import Base


def test_skill_package_model_fields_exist():
    from app.tenants.models import SkillPackage

    table = SkillPackage.__table__
    assert table.name == "skill_packages"

    columns = {c.name: c for c in table.columns}
    expected = {"id", "owner_type", "client_id", "name", "created_at", "updated_at"}
    assert expected.issubset(columns), f"Missing columns: {expected - set(columns)}"

    assert columns["client_id"].nullable is True
    fk_targets = {str(fk.column) for fk in columns["client_id"].foreign_keys}
    assert "clients.id" in fk_targets


def test_skill_model_fields_exist():
    from app.tenants.models import Skill

    table = Skill.__table__
    assert table.name == "skills"

    columns = {c.name: c for c in table.columns}
    expected = {
        "id",
        "package_id",
        "slug",
        "section",
        "agent_id",
        "active_revision_id",
    }
    assert expected.issubset(columns), f"Missing columns: {expected - set(columns)}"

    assert columns["package_id"].foreign_keys
    assert "skill_packages.id" in {
        str(fk.column) for fk in columns["package_id"].foreign_keys
    }
    assert columns["agent_id"].nullable is True
    assert "agents.id" in {str(fk.column) for fk in columns["agent_id"].foreign_keys}
    assert "skill_revisions.id" in {
        str(fk.column) for fk in columns["active_revision_id"].foreign_keys
    }

    unique_constraints = [
        c for c in table.constraints if c.__class__.__name__ == "UniqueConstraint"
    ]
    assert any(
        {col.name for col in uc.columns} == {"package_id", "slug", "agent_id"}
        for uc in unique_constraints
    ), "expected a unique(package_id, slug, agent_id) constraint"


def test_skill_revision_model_fields_exist():
    from app.tenants.models import SkillRevision

    table = SkillRevision.__table__
    assert table.name == "skill_revisions"

    columns = {c.name: c for c in table.columns}
    expected = {
        "id",
        "skill_id",
        "revision_number",
        "content_md",
        "filler_text",
        "trigger_hint",
        "description",
        "source",
        "created_by",
        "created_at",
        "note",
    }
    assert expected.issubset(columns), f"Missing columns: {expected - set(columns)}"

    assert "skills.id" in {str(fk.column) for fk in columns["skill_id"].foreign_keys}

    unique_constraints = [
        c for c in table.constraints if c.__class__.__name__ == "UniqueConstraint"
    ]
    assert any(
        {col.name for col in uc.columns} == {"skill_id", "revision_number"}
        for uc in unique_constraints
    ), "expected a unique(skill_id, revision_number) constraint"


def test_skill_package_models_registered_on_base_metadata():
    from app.tenants import models  # noqa: F401

    assert "skill_packages" in Base.metadata.tables
    assert "skills" in Base.metadata.tables
    assert "skill_revisions" in Base.metadata.tables
