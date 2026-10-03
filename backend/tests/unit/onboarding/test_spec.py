"""Task 4.1 — OnboardingSpec / CrmIntegrationSpec reject unknown and secret fields."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_onboarding_spec_rejects_unknown_field():
    from app.onboarding.spec import OnboardingSpec

    base = dict(
        client_id="acme",
        client_name="Acme Co",
        client_language="Spanish",
        agent_slug="jaumpablo",
        agent_name="Jaumpablo",
        agent_goal="Sell insurance",
        agent_system_prompt="You are a helpful agent.",
        agent_voice_id="voice-1",
    )

    with pytest.raises(ValidationError):
        OnboardingSpec(**base, api_key="should-not-be-accepted")


def test_crm_integration_spec_has_no_secret_field():
    from app.onboarding.spec import CrmIntegrationSpec

    forbidden_names = {"api_key", "secret", "token", "ciphertext", "password"}
    field_names = set(CrmIntegrationSpec.model_fields.keys())
    assert field_names.isdisjoint(forbidden_names)

    with pytest.raises(ValidationError):
        CrmIntegrationSpec(
            provider="airtable",
            base_id="appXXXXXXXXXXXXXX",
            table_id="tblXXXXXXXXXXXXXX",
            field_mappings={"name": "Name"},
            api_key="sk-this-is-a-secret",
        )
