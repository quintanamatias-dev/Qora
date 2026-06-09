"""Unit tests for is_quote_ready() — pure function, driven by CRM config.

TDD WU-4 task 4.1: RED → GREEN → TRIANGULATE → REFACTOR

Spec requirements covered:
- QR-1: all quote_ready_fields must be present and non-empty in custom_fields
- QR-2: empty/absent quote_ready_fields → always False
- QR-5: no crm.yaml → never quoted (caller passes empty list or None)
- AC-4: is_quote_ready driven solely by crm.yaml; no hardcoded field names
- AC-10: client with no crm.yaml / empty quote_ready_fields never reaches "quoted"
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# 4.1 RED — new pure function signature:
#   is_quote_ready(custom_fields: dict[str, str], quote_ready_fields: list[str]) -> bool
# ---------------------------------------------------------------------------


class TestIsQuoteReadyPureFunction:
    """Tests for the refactored pure is_quote_ready() function."""

    def test_all_required_fields_present_returns_true(self):
        """QR-1: all quote_ready_fields present and non-empty → True."""
        from app.summarizer import is_quote_ready

        custom_fields = {
            "car_make": "Toyota",
            "car_model": "Corolla",
            "car_year": "2021",
            "age": "35",
            "zona": "Norte",
        }
        quote_ready_fields = ["car_make", "car_model", "car_year", "age", "zona"]
        assert is_quote_ready(custom_fields, quote_ready_fields) is True

    def test_one_required_field_missing_returns_false(self):
        """QR-1: one required field absent → False."""
        from app.summarizer import is_quote_ready

        custom_fields = {
            "car_make": "Toyota",
            "car_model": "Corolla",
            "car_year": "2021",
            "age": "35",
            # zona is absent
        }
        quote_ready_fields = ["car_make", "car_model", "car_year", "age", "zona"]
        assert is_quote_ready(custom_fields, quote_ready_fields) is False

    def test_empty_quote_ready_fields_returns_false(self):
        """QR-2: quote_ready_fields empty list → always False (never infer quoted)."""
        from app.summarizer import is_quote_ready

        custom_fields = {"car_make": "Toyota", "age": "30"}
        assert is_quote_ready(custom_fields, []) is False

    def test_none_quote_ready_fields_returns_false(self):
        """QR-2: quote_ready_fields=None → always False (safe degradation)."""
        from app.summarizer import is_quote_ready

        custom_fields = {"car_make": "Toyota", "age": "30"}
        assert is_quote_ready(custom_fields, None) is False  # type: ignore[arg-type]

    def test_field_present_but_empty_string_returns_false(self):
        """QR-1: field present but empty string → not satisfied → False."""
        from app.summarizer import is_quote_ready

        custom_fields = {
            "car_make": "Toyota",
            "car_model": "",  # present but empty
            "car_year": "2021",
            "age": "35",
            "zona": "Norte",
        }
        quote_ready_fields = ["car_make", "car_model", "car_year", "age", "zona"]
        assert is_quote_ready(custom_fields, quote_ready_fields) is False

    def test_missing_crm_yaml_client_never_quoted(self):
        """QR-5: caller passes [] when client has no crm.yaml → always False."""
        from app.summarizer import is_quote_ready

        # Client has no crm.yaml; caller passes empty list
        custom_fields = {"car_make": "Ford", "age": "40", "zona": "Sur"}
        assert is_quote_ready(custom_fields, []) is False

    def test_subset_of_fields_only_partially_satisfied(self):
        """QR-1 triangulation: only 3 of 5 required fields present → False."""
        from app.summarizer import is_quote_ready

        custom_fields = {
            "car_make": "Volkswagen",
            "car_year": "2019",
            "zona": "Centro",
        }
        quote_ready_fields = ["car_make", "car_model", "car_year", "age", "zona"]
        assert is_quote_ready(custom_fields, quote_ready_fields) is False

    def test_single_required_field_satisfied(self):
        """Minimal quote_ready_fields=[field] and field is present → True."""
        from app.summarizer import is_quote_ready

        custom_fields = {"age": "42"}
        assert is_quote_ready(custom_fields, ["age"]) is True

    def test_extra_custom_fields_dont_affect_result(self):
        """Extra fields in custom_fields beyond required list are ignored."""
        from app.summarizer import is_quote_ready

        custom_fields = {
            "car_make": "Ford",
            "car_year": "2020",
            "extra_field": "some_value",
            "another_extra": "yes",
        }
        quote_ready_fields = ["car_make", "car_year"]
        assert is_quote_ready(custom_fields, quote_ready_fields) is True


# ---------------------------------------------------------------------------
# apply_status_from_next_action integration: uses new is_quote_ready signature
# ---------------------------------------------------------------------------


class TestApplyStatusWithCustomFields:
    """Tests for apply_status_from_next_action calling new is_quote_ready.

    The caller must now pass a dict-like object with custom_fields and
    quote_ready_fields so is_quote_ready works via the new pure signature.
    """

    def test_apply_status_returns_quoted_when_quote_ready(self):
        """apply_status_from_next_action → 'quoted' when all required fields present.

        Uses the new is_quote_ready(custom_fields, quote_ready_fields) internally.
        Caller passes a custom_fields dict and quote_ready_fields list in the context.
        """
        from app.summarizer import apply_status_from_next_action

        # Caller provides custom_fields dict and quote_ready_fields to is_quote_ready check
        custom_fields = {
            "car_make": "Toyota",
            "car_model": "Corolla",
            "car_year": "2021",
            "age": "35",
            "zona": "Norte",
        }
        quote_ready_fields = ["car_make", "car_model", "car_year", "age", "zona"]

        next_action = {
            "action": "close_lead",
            "outcome": {"classification": "completed_positive"},
        }
        result = apply_status_from_next_action(
            current_status="called",
            next_action_result=next_action,
            custom_fields=custom_fields,
            quote_ready_fields=quote_ready_fields,
        )
        assert result == "quoted"

    def test_apply_status_returns_follow_up_when_not_quote_ready(self):
        """apply_status_from_next_action → 'follow_up' when required fields missing."""
        from app.summarizer import apply_status_from_next_action

        custom_fields = {"car_make": "Toyota"}  # zona, car_model, etc. missing
        quote_ready_fields = ["car_make", "car_model", "car_year", "age", "zona"]

        next_action = {
            "action": "close_lead",
            "outcome": {"classification": "completed_positive"},
        }
        result = apply_status_from_next_action(
            current_status="called",
            next_action_result=next_action,
            custom_fields=custom_fields,
            quote_ready_fields=quote_ready_fields,
        )
        assert result == "follow_up"

    def test_apply_status_returns_follow_up_when_no_crm_config(self):
        """QR-5: no crm.yaml → quote_ready_fields=[] → always follow_up for positive outcomes."""
        from app.summarizer import apply_status_from_next_action

        custom_fields = {"car_make": "Ford", "car_year": "2020"}
        next_action = {
            "action": "close_lead",
            "outcome": {"classification": "completed_positive"},
        }
        result = apply_status_from_next_action(
            current_status="called",
            next_action_result=next_action,
            custom_fields=custom_fields,
            quote_ready_fields=[],  # no crm.yaml → empty
        )
        assert result == "follow_up"
