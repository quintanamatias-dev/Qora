"""Tests for Lead model schema — external_lead_id column.

TDD: task 1.1 RED — assert Lead has external_lead_id Integer nullable column.
"""

from __future__ import annotations

from sqlalchemy import inspect


# ---------------------------------------------------------------------------
# Task 1.1 — RED: Lead model has external_lead_id Integer nullable column
# ---------------------------------------------------------------------------


def test_lead_model_has_external_lead_id_column():
    """Lead model must declare external_lead_id as Integer, nullable.

    GIVEN the Lead SQLAlchemy model
    WHEN the column metadata is inspected
    THEN external_lead_id exists, is Integer type, and is nullable.
    """
    from app.leads.models import Lead

    mapper = inspect(Lead)
    column_names = {col.key for col in mapper.mapper.column_attrs}
    assert "external_lead_id" in column_names, (
        "Lead model must have external_lead_id column"
    )

    # Check the actual SQLAlchemy column type and nullable flag
    table_columns = {col.name: col for col in mapper.mapper.mapped_table.columns}
    assert "external_lead_id" in table_columns, (
        "external_lead_id must be a mapped table column"
    )
    col = table_columns["external_lead_id"]
    assert col.nullable is True, "external_lead_id must be nullable"

    from sqlalchemy import Integer as SAInteger

    assert isinstance(col.type, SAInteger), (
        f"external_lead_id must be Integer type, got {type(col.type).__name__}"
    )


def test_lead_model_external_lead_id_default_is_none():
    """Lead instances must default external_lead_id to None.

    GIVEN a freshly constructed Lead (not yet persisted)
    WHEN external_lead_id is not provided
    THEN it defaults to None.
    """
    from app.leads.models import Lead

    lead = Lead(
        id="test-id",
        client_id="test-client",
        name="Test Lead",
        phone="+5491100000000",
    )
    assert lead.external_lead_id is None, (
        "external_lead_id must default to None when not provided"
    )


def test_lead_model_external_lead_id_stores_integer():
    """Lead.external_lead_id must accept integer values (Meta numeric IDs).

    GIVEN a Lead instance
    WHEN external_lead_id is set to a numeric value
    THEN it stores the integer without coercion to string.
    """
    from app.leads.models import Lead

    lead = Lead(
        id="test-id-2",
        client_id="test-client",
        name="Test Lead 2",
        phone="+5491100000001",
        external_lead_id=123456,
    )
    assert lead.external_lead_id == 123456
    assert isinstance(lead.external_lead_id, int), (
        "external_lead_id must remain an integer, not be coerced to string"
    )
