"""Onboarding harness — declarative spec shape (design.md M-D2).

No field anywhere in this module accepts a secret/credential value (M-D2:
"No secret field in the onboarding spec"). CrmIntegrationSpec's
``legacy_env_var_name`` is a NAME the integration resolves at read time via
``app.integrations.crm_config.CRMConfig.resolve_api_key_async`` — never the
secret value itself. A client's actual CRM API key, if needed, is written
afterward via the existing write-only
``PUT /clients/{client_id}/integrations/{provider}/secret`` endpoint.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class CrmIntegrationSpec(BaseModel):
    """Non-secret CRM integration config, mirroring client_integrations.config."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["airtable"]
    base_id: str
    table_id: str
    match_field: str = "lead_id"
    field_mappings: dict[str, str] = {}
    legacy_env_var_name: str | None = None


class OnboardingSpec(BaseModel):
    """One client + one agent to provision (design.md M-D2 interface contract)."""

    model_config = ConfigDict(extra="forbid")

    client_id: str
    client_name: str
    client_language: str

    agent_slug: str
    agent_name: str
    agent_goal: str
    agent_system_prompt: str
    agent_voice_id: str
    elevenlabs_agent_id: str | None = None

    analysis_vertical: Literal["insurance", "generic"] | None = None
    crm_integration: CrmIntegrationSpec | None = None
