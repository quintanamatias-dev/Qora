"""Unit tests for quote-ready status changes.

Covers:
- Task 1: Lead model has `zona` column (String, nullable)
- Task 2: LeadStatus enum has `quoted` value + VALID_TRANSITIONS
- Task 3: _QUINTANA_TOOL_CONFIG includes age+zona fields
- Task 4: is_quote_ready() pure function
- Task 5: apply_status_from_next_action returns "quoted" or "follow_up" for
          completed_positive outcome depending on is_quote_ready result
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Task 1: zona column on Lead model
# ---------------------------------------------------------------------------


def test_lead_model_has_zona_column():
    """Lead model must expose a `zona` attribute (String, nullable)."""
    from app.leads.models import Lead
    from sqlalchemy.orm import class_mapper

    mapper = class_mapper(Lead)
    col_names = {c.key for c in mapper.columns}
    assert "zona" in col_names, "Lead model must have a `zona` column"


def test_lead_zona_is_nullable():
    """Lead.zona column must be nullable=True."""
    from app.leads.models import Lead
    from sqlalchemy.orm import class_mapper

    mapper = class_mapper(Lead)
    col = mapper.columns["zona"]
    assert col.nullable is True, "Lead.zona must be nullable"


def test_lead_zona_is_string_type():
    """Lead.zona must be a String type."""
    from app.leads.models import Lead
    from sqlalchemy.orm import class_mapper
    from sqlalchemy import String

    mapper = class_mapper(Lead)
    col = mapper.columns["zona"]
    assert isinstance(col.type, String), f"Expected String, got {type(col.type)}"


# ---------------------------------------------------------------------------
# Task 2: quoted in LeadStatus + VALID_TRANSITIONS
# ---------------------------------------------------------------------------


def test_lead_status_has_quoted():
    """LeadStatus enum must include QUOTED = 'quoted'."""
    from app.leads.models import LeadStatus

    assert hasattr(LeadStatus, "QUOTED"), "LeadStatus must have QUOTED member"
    assert LeadStatus.QUOTED.value == "quoted"


def test_quoted_is_between_called_and_interested():
    """Logical ordering: called → quoted is a valid transition."""
    from app.leads.models import LeadStatus, VALID_TRANSITIONS

    assert LeadStatus.QUOTED in VALID_TRANSITIONS.get(LeadStatus.CALLED, set()), (
        "CALLED → QUOTED must be a valid transition"
    )


def test_quoted_is_terminal():
    """quoted is a terminal state — no further transitions allowed from it."""
    from app.leads.models import LeadStatus, VALID_TRANSITIONS

    transitions_from_quoted = VALID_TRANSITIONS.get(LeadStatus.QUOTED, set())
    assert len(transitions_from_quoted) == 0, (
        f"quoted should be terminal, but found transitions: {transitions_from_quoted}"
    )


def test_is_valid_transition_called_to_quoted():
    """is_valid_transition must accept 'called' → 'quoted'."""
    from app.leads.models import is_valid_transition

    assert is_valid_transition("called", "quoted") is True


def test_is_valid_transition_quoted_to_anything_is_false():
    """is_valid_transition must reject any transition from 'quoted'."""
    from app.leads.models import is_valid_transition

    for target in ["new", "called", "interested", "not_interested", "follow_up"]:
        assert is_valid_transition("quoted", target) is False, (
            f"quoted → {target} should be rejected"
        )


# ---------------------------------------------------------------------------
# Task 3 (WU-5 updated): Dynamic schema from field_definitions includes age + zona
# _QUINTANA_TOOL_CONFIG was removed in WU-5 — schema now comes from crm.yaml
# ---------------------------------------------------------------------------


def test_dynamic_schema_from_crm_config_has_age():
    """Dynamic capture_data schema from CRMConfig must include 'age' field.

    WU-5: Schema generated from field_definitions, not _QUINTANA_TOOL_CONFIG.
    """
    from app.tools.registry import build_capture_data_from_field_definitions
    from app.integrations.crm_config import CRMConfig, CustomFieldDef

    crm_config = CRMConfig(
        provider="airtable",
        base_id="app_q",
        table_id="tbl_q",
        api_key="LITERAL_KEY",
        match_field="lead_id",
        custom_fields=[
            CustomFieldDef(field_key="car_make", field_type="string", label="Car Make"),
            CustomFieldDef(field_key="age", field_type="integer", label="Age"),
            CustomFieldDef(field_key="zona", field_type="string", label="Zone"),
        ],
    )
    result = build_capture_data_from_field_definitions(crm_config)
    assert result is not None
    props = result["function"]["parameters"]["properties"]
    assert "age" in props, "dynamic schema must include 'age' field"
    assert props["age"]["type"] == "integer"


def test_dynamic_schema_from_crm_config_has_zona():
    """Dynamic capture_data schema from CRMConfig must include 'zona' field.

    WU-5: Schema generated from field_definitions, not _QUINTANA_TOOL_CONFIG.
    """
    from app.tools.registry import build_capture_data_from_field_definitions
    from app.integrations.crm_config import CRMConfig, CustomFieldDef

    crm_config = CRMConfig(
        provider="airtable",
        base_id="app_q",
        table_id="tbl_q",
        api_key="LITERAL_KEY",
        match_field="lead_id",
        custom_fields=[
            CustomFieldDef(field_key="zona", field_type="string", label="Zone"),
        ],
    )
    result = build_capture_data_from_field_definitions(crm_config)
    assert result is not None
    props = result["function"]["parameters"]["properties"]
    assert "zona" in props, "dynamic schema must include 'zona' field"
    assert props["zona"]["type"] == "string"


def test_dynamic_schema_lead_id_always_required():
    """Dynamic schema always includes lead_id in required, regardless of field_definitions.

    WU-5: lead_id is always required for handler lookup.
    """
    from app.tools.registry import build_capture_data_from_field_definitions
    from app.integrations.crm_config import CRMConfig, CustomFieldDef

    crm_config = CRMConfig(
        provider="airtable",
        base_id="app_q",
        table_id="tbl_q",
        api_key="LITERAL_KEY",
        match_field="lead_id",
        custom_fields=[
            CustomFieldDef(field_key="car_make", field_type="string", label="Car Make"),
            CustomFieldDef(field_key="car_model", field_type="string", label="Car Model"),
            CustomFieldDef(field_key="car_year", field_type="integer", label="Car Year"),
            CustomFieldDef(field_key="age", field_type="integer", label="Age"),
            CustomFieldDef(field_key="zona", field_type="string", label="Zone"),
        ],
    )
    result = build_capture_data_from_field_definitions(crm_config)
    assert result is not None
    required = result["function"]["parameters"]["required"]
    assert "lead_id" in required, "lead_id must always be in required list"


# ---------------------------------------------------------------------------
# Task 4: is_quote_ready() pure function — new signature (WU-4)
# ---------------------------------------------------------------------------
# New API: is_quote_ready(custom_fields: dict[str, str], quote_ready_fields: list[str]) -> bool
# These tests verify the new config-driven pure function behavior.
# (Old Lead-ORM-based tests removed — new tests in tests/unit/test_quote_ready.py)

_QUINTANA_QR_FIELDS = ["car_make", "car_model", "car_year", "age", "zona"]


def test_is_quote_ready_returns_true_when_all_fields_present():
    """is_quote_ready() → True when all required fields present in custom_fields."""
    from app.summarizer import is_quote_ready

    custom_fields = {
        "car_make": "Toyota",
        "car_model": "Corolla",
        "car_year": "2020",
        "age": "35",
        "zona": "Palermo",
    }
    assert is_quote_ready(custom_fields, _QUINTANA_QR_FIELDS) is True


def test_is_quote_ready_returns_false_when_zona_missing():
    """is_quote_ready() → False when zona is absent from custom_fields."""
    from app.summarizer import is_quote_ready

    custom_fields = {
        "car_make": "Toyota",
        "car_model": "Corolla",
        "car_year": "2020",
        "age": "35",
    }
    assert is_quote_ready(custom_fields, _QUINTANA_QR_FIELDS) is False


def test_is_quote_ready_returns_false_when_age_missing():
    """is_quote_ready() → False when age is absent from custom_fields."""
    from app.summarizer import is_quote_ready

    custom_fields = {
        "car_make": "Toyota",
        "car_model": "Corolla",
        "car_year": "2020",
        "zona": "San Telmo",
    }
    assert is_quote_ready(custom_fields, _QUINTANA_QR_FIELDS) is False


def test_is_quote_ready_returns_false_when_car_make_missing():
    """is_quote_ready() → False when car_make is absent from custom_fields."""
    from app.summarizer import is_quote_ready

    custom_fields = {
        "car_model": "Corolla",
        "car_year": "2020",
        "age": "35",
        "zona": "Recoleta",
    }
    assert is_quote_ready(custom_fields, _QUINTANA_QR_FIELDS) is False


def test_is_quote_ready_returns_false_when_car_model_missing():
    """is_quote_ready() → False when car_model is absent from custom_fields."""
    from app.summarizer import is_quote_ready

    custom_fields = {
        "car_make": "Toyota",
        "car_year": "2020",
        "age": "35",
        "zona": "Recoleta",
    }
    assert is_quote_ready(custom_fields, _QUINTANA_QR_FIELDS) is False


def test_is_quote_ready_returns_false_when_car_year_missing():
    """is_quote_ready() → False when car_year is absent from custom_fields."""
    from app.summarizer import is_quote_ready

    custom_fields = {
        "car_make": "Toyota",
        "car_model": "Corolla",
        "age": "35",
        "zona": "Recoleta",
    }
    assert is_quote_ready(custom_fields, _QUINTANA_QR_FIELDS) is False


def test_is_quote_ready_returns_false_when_all_missing():
    """is_quote_ready() → False when custom_fields is empty."""
    from app.summarizer import is_quote_ready

    assert is_quote_ready({}, _QUINTANA_QR_FIELDS) is False


# ---------------------------------------------------------------------------
# Task 5: apply_status_from_next_action updated logic (WU-4)
# ---------------------------------------------------------------------------
# New API: pass custom_fields + quote_ready_fields (config-driven).
# When action=close_lead + completed_positive:
#   - all quote_ready_fields present in custom_fields → "quoted"
#   - any missing → "follow_up"
#   - quote_ready_fields=[] (no crm.yaml) → "follow_up"


def _make_close_lead_positive() -> dict:
    return {
        "action": "close_lead",
        "outcome": {"classification": "completed_positive"},
    }


def _make_close_lead_negative() -> dict:
    return {
        "action": "close_lead",
        "outcome": {"classification": "completed_negative"},
    }


def _make_follow_up_action() -> dict:
    return {"action": "follow_up"}


_ALL_FIELDS_CF = {
    "car_make": "Toyota",
    "car_model": "Corolla",
    "car_year": "2020",
    "age": "35",
    "zona": "Palermo",
}


def test_apply_status_quoted_when_quote_ready():
    """close_lead + completed_positive + all fields present → 'quoted'."""
    from app.summarizer import apply_status_from_next_action

    result = apply_status_from_next_action(
        current_status="called",
        next_action_result=_make_close_lead_positive(),
        custom_fields=_ALL_FIELDS_CF,
        quote_ready_fields=_QUINTANA_QR_FIELDS,
    )
    assert result == "quoted"


def test_apply_status_follow_up_when_not_quote_ready():
    """close_lead + completed_positive + missing zona → 'follow_up'."""
    from app.summarizer import apply_status_from_next_action

    result = apply_status_from_next_action(
        current_status="called",
        next_action_result=_make_close_lead_positive(),
        custom_fields={"car_make": "Toyota", "car_model": "Corolla", "car_year": "2020", "age": "35"},
        quote_ready_fields=_QUINTANA_QR_FIELDS,
    )
    assert result == "follow_up"


def test_apply_status_follow_up_when_lead_is_none():
    """close_lead + completed_positive + no custom_fields → 'follow_up'."""
    from app.summarizer import apply_status_from_next_action

    result = apply_status_from_next_action(
        current_status="called",
        next_action_result=_make_close_lead_positive(),
        # No custom_fields or quote_ready_fields → follow_up
    )
    assert result == "follow_up"


def test_apply_status_not_interested_still_works():
    """Negative outcomes → 'not_interested' regardless of lead state."""
    from app.summarizer import apply_status_from_next_action

    result = apply_status_from_next_action(
        current_status="called",
        next_action_result=_make_close_lead_negative(),
        custom_fields=_ALL_FIELDS_CF,
        quote_ready_fields=_QUINTANA_QR_FIELDS,
    )
    assert result == "not_interested"


def test_apply_status_follow_up_action_unchanged():
    """follow_up action → 'follow_up' regardless of lead state."""
    from app.summarizer import apply_status_from_next_action

    result = apply_status_from_next_action(
        current_status="called",
        next_action_result=_make_follow_up_action(),
        custom_fields=_ALL_FIELDS_CF,
        quote_ready_fields=_QUINTANA_QR_FIELDS,
    )
    assert result == "follow_up"


def test_apply_status_non_called_still_none():
    """When current_status != 'called' → None regardless of lead state."""
    from app.summarizer import apply_status_from_next_action

    result = apply_status_from_next_action(
        current_status="new",
        next_action_result=_make_close_lead_positive(),
        custom_fields=_ALL_FIELDS_CF,
        quote_ready_fields=_QUINTANA_QR_FIELDS,
    )
    assert result is None


def test_apply_status_backward_compat_no_lead_kwarg():
    """Calling without lead kwarg (old callers) must still work for non-positive outcomes."""
    from app.summarizer import apply_status_from_next_action

    # follow_up action — no lead needed
    result = apply_status_from_next_action(
        current_status="called",
        next_action_result=_make_follow_up_action(),
    )
    assert result == "follow_up"
