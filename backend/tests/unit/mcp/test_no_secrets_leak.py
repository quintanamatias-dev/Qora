"""Task 1.3 (re-run by 2.2/3.3) — never-secrets guard.

Two layers: a static schema-shape check (no registered tool's output model
has a field name matching a secret-shaped pattern) and a dynamic check
against seeded data (a client with a real encrypted ClientSecret) — neither
list_clients/get_client/list_agents/get_agent ever surfaces that value,
because AgentEffectiveConfig/ClientSummary have no field for it at all.
"""

from __future__ import annotations

import re

import pytest
from cryptography.fernet import Fernet
from pydantic import BaseModel

_FORBIDDEN_FIELD_PATTERN = re.compile(r"(key|secret|token|ciphertext)", re.IGNORECASE)

_PLAINTEXT_SECRET = "sekrit-plaintext-value-should-never-leak"


def _iter_model_field_names(model: type) -> set[str]:
    """Recursively collect every field name reachable from a Pydantic model,
    including fields nested inside dict[str, OtherModel] / list[OtherModel]."""
    names: set[str] = set()
    seen_models: set[type] = set()

    def _walk(m: type) -> None:
        if m in seen_models or not (isinstance(m, type) and issubclass(m, BaseModel)):
            return
        seen_models.add(m)
        for field_name, field in m.model_fields.items():
            names.add(field_name)
            for arg in getattr(field.annotation, "__args__", ()) or ():
                if isinstance(arg, type) and issubclass(arg, BaseModel):
                    _walk(arg)
            if isinstance(field.annotation, type) and issubclass(field.annotation, BaseModel):
                _walk(field.annotation)

    _walk(model)
    return names


def test_no_registered_tool_output_contains_secret_shaped_field():
    from app.mcp.server import REGISTERED_TOOLS

    for spec in REGISTERED_TOOLS:
        field_names = _iter_model_field_names(spec.output_model)
        violations = [n for n in field_names if _FORBIDDEN_FIELD_PATTERN.search(n)]
        assert not violations, (
            f"tool {spec.name!r} output model {spec.output_model!r} has "
            f"secret-shaped field(s): {violations}"
        )


def test_exactly_eight_tools_are_registered():
    from app.mcp.server import REGISTERED_TOOLS

    assert len(REGISTERED_TOOLS) == 8
    assert len({spec.name for spec in REGISTERED_TOOLS}) == 8


def _assert_no_secret_in_value(value, path: str = "$") -> None:
    """Recursively check only VALUES for a leaked secret.

    Key names are intentionally NOT checked here: the `config` dict's keys
    come from FIELD_POLICY (a fixed, reviewed registry — e.g. 'max_tokens'),
    not attacker/caller-controlled data, so a substring match on 'token'
    would be a false positive. The static schema-shape test above already
    covers declared Pydantic field names.
    """
    if isinstance(value, dict):
        for k, v in value.items():
            _assert_no_secret_in_value(v, f"{path}.{k}")
    elif isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            _assert_no_secret_in_value(item, f"{path}[{i}]")
    elif isinstance(value, str):
        assert _PLAINTEXT_SECRET not in value, f"plaintext secret leaked at {path}"


@pytest.mark.asyncio
async def test_get_agent_never_leaks_a_configured_client_secret(db_session, monkeypatch):
    from app.core.crypto import get_secret_crypto
    from app.mcp.tools.agents import get_agent
    from app.mcp.tools.clients import get_client, list_clients
    from app.tenants import service as tenant_service
    from app.tenants.models import ClientIntegration, ClientSecret

    monkeypatch.setenv("QORA_SECRETS_MASTER_KEY", Fernet.generate_key().decode())

    client = await tenant_service.create_client(
        db_session, id="secret-client", name="Secret Client", voice_id="voice-1"
    )
    agents = await tenant_service.list_agents_for_client(db_session, client.id)
    agent = agents[0]

    crypto = get_secret_crypto()
    assert crypto is not None
    ciphertext, key_id = crypto.encrypt(_PLAINTEXT_SECRET)

    integration = ClientIntegration(
        client_id=client.id,
        provider="airtable",
        enabled=True,
        config='{"base_id": "appXXX", "table_id": "tblYYY", "field_mappings": {}}',
        status="ok",
        created_by="test",
        updated_by="test",
    )
    db_session.add(integration)
    await db_session.flush()
    db_session.add(
        ClientSecret(
            client_id=client.id,
            integration_id=integration.id,
            name="airtable_api_key",
            ciphertext=ciphertext,
            key_id=key_id,
            created_by="test",
            updated_by="test",
        )
    )
    await db_session.commit()

    agent_config = await get_agent(db_session, client.id, agent.id)
    client_summary = await get_client(db_session, client.id)
    client_list = await list_clients(db_session)

    assert agent_config is not None
    _assert_no_secret_in_value(agent_config.model_dump())
    _assert_no_secret_in_value(client_summary.model_dump())
    for c in client_list:
        _assert_no_secret_in_value(c.model_dump())
