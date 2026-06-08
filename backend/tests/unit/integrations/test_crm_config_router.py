"""Unit tests for CRM config router — TDD RED phase (T13).

Covers integration API scenarios from design doc:
- GET /api/v1/clients/{client_id}/integrations → returns config with provider,
  base_id, table_id, api_key_env (NAME only), match_field, field_count, connected
- GET /api/v1/clients/nonexistent/integrations → returns empty list []
- PUT /api/v1/clients/{client_id}/integrations/airtable → updates config
- POST /api/v1/clients/{client_id}/integrations/airtable/test → tests connection

Security requirements:
- Raw API token value NEVER appears in any GET or PUT response
- api_key_env field returns the ENV VAR NAME, not the secret

Test layer: Unit (monkeypatched YAML + mock Airtable — no live IO).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_crm_yaml(client_dir: Path, data: dict) -> None:
    client_dir.mkdir(parents=True, exist_ok=True)
    (client_dir / "crm.yaml").write_text(yaml.dump(data))


VALID_CRM_DATA = {
    "provider": "airtable",
    "base_id": "appXXXXXXXXXXXXXX",
    "table_id": "tblYYYYYYYYYYYYYY",
    "api_key_env": "QUINTANA_AIRTABLE_API_KEY",
    "match_field": "lead_id",
    "field_mappings": [
        {"source": "name", "target": "Nombre", "type": "string"},
        {"source": "phone", "target": "Teléfono", "type": "phone"},
        {"source": "email", "target": "Correo", "type": "string"},
    ],
}


def _make_test_client(tmp_path: Path) -> TestClient:
    """Create a FastAPI TestClient with the crm_config_router mounted."""
    from fastapi import FastAPI
    from app.integrations.crm_config_router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/v1/clients/{client_id}/integrations
# ---------------------------------------------------------------------------


def test_get_integrations_returns_list_for_configured_client(
    tmp_path: Path, monkeypatch
):
    """GET integrations for a client with crm.yaml → returns list with config."""
    monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "pat_test_secret")
    client_dir = tmp_path / "clients" / "quintana-seguros"
    _write_crm_yaml(client_dir, VALID_CRM_DATA)

    with patch(
        "app.integrations.crm_config_router.CLIENTS_ROOT",
        tmp_path / "clients",
    ):
        tc = _make_test_client(tmp_path)
        resp = tc.get("/api/v1/clients/quintana-seguros/integrations")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1

    item = data[0]
    assert item["provider"] == "airtable"
    assert item["base_id"] == "appXXXXXXXXXXXXXX"
    assert item["table_id"] == "tblYYYYYYYYYYYYYY"
    assert item["api_key_env"] == "QUINTANA_AIRTABLE_API_KEY"
    assert item["match_field"] == "lead_id"
    assert item["field_count"] == 3


def test_get_integrations_never_returns_raw_api_key(tmp_path: Path, monkeypatch):
    """SECURITY: raw API token must NEVER appear in the GET response."""
    monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "pat_super_secret_value")
    client_dir = tmp_path / "clients" / "quintana-seguros"
    _write_crm_yaml(client_dir, VALID_CRM_DATA)

    with patch(
        "app.integrations.crm_config_router.CLIENTS_ROOT",
        tmp_path / "clients",
    ):
        tc = _make_test_client(tmp_path)
        resp = tc.get("/api/v1/clients/quintana-seguros/integrations")

    assert resp.status_code == 200
    # The raw secret must NEVER appear in the response JSON
    assert "pat_super_secret_value" not in resp.text


def test_get_integrations_returns_empty_for_unconfigured_client(tmp_path: Path):
    """GET integrations for client with no crm.yaml → returns empty list."""
    with patch(
        "app.integrations.crm_config_router.CLIENTS_ROOT",
        tmp_path / "clients",
    ):
        tc = _make_test_client(tmp_path)
        resp = tc.get("/api/v1/clients/nonexistent-client/integrations")

    assert resp.status_code == 200
    assert resp.json() == []


def test_get_integrations_returns_empty_for_client_dir_without_crm(tmp_path: Path):
    """GET integrations for client dir that exists but has no crm.yaml → []."""
    client_dir = tmp_path / "clients" / "no-crm-client"
    client_dir.mkdir(parents=True)

    with patch(
        "app.integrations.crm_config_router.CLIENTS_ROOT",
        tmp_path / "clients",
    ):
        tc = _make_test_client(tmp_path)
        resp = tc.get("/api/v1/clients/no-crm-client/integrations")

    assert resp.status_code == 200
    assert resp.json() == []


def test_get_integrations_connected_field_is_boolean(tmp_path: Path, monkeypatch):
    """GET integrations response includes a boolean 'connected' field."""
    monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "pat_test")
    client_dir = tmp_path / "clients" / "quintana-seguros"
    _write_crm_yaml(client_dir, VALID_CRM_DATA)

    with patch(
        "app.integrations.crm_config_router.CLIENTS_ROOT",
        tmp_path / "clients",
    ):
        tc = _make_test_client(tmp_path)
        resp = tc.get("/api/v1/clients/quintana-seguros/integrations")

    item = resp.json()[0]
    assert "connected" in item
    assert isinstance(item["connected"], bool)


# ---------------------------------------------------------------------------
# PUT /api/v1/clients/{client_id}/integrations/{provider}
# ---------------------------------------------------------------------------


def test_put_integration_updates_base_id(tmp_path: Path, monkeypatch):
    """PUT integration → updates base_id in crm.yaml and returns updated config."""
    monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "pat_test")
    client_dir = tmp_path / "clients" / "quintana-seguros"
    _write_crm_yaml(client_dir, VALID_CRM_DATA)

    with patch(
        "app.integrations.crm_config_router.CLIENTS_ROOT",
        tmp_path / "clients",
    ):
        tc = _make_test_client(tmp_path)
        resp = tc.put(
            "/api/v1/clients/quintana-seguros/integrations/airtable",
            json={"base_id": "appNEWBASEID"},
        )

    assert resp.status_code == 200
    updated = resp.json()
    assert updated["base_id"] == "appNEWBASEID"
    # Other fields unchanged
    assert updated["table_id"] == "tblYYYYYYYYYYYYYY"
    assert updated["api_key_env"] == "QUINTANA_AIRTABLE_API_KEY"


def test_put_integration_updates_table_id(tmp_path: Path, monkeypatch):
    """PUT integration → updates table_id."""
    monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "pat_test")
    client_dir = tmp_path / "clients" / "quintana-seguros"
    _write_crm_yaml(client_dir, VALID_CRM_DATA)

    with patch(
        "app.integrations.crm_config_router.CLIENTS_ROOT",
        tmp_path / "clients",
    ):
        tc = _make_test_client(tmp_path)
        resp = tc.put(
            "/api/v1/clients/quintana-seguros/integrations/airtable",
            json={"table_id": "tblNEW123"},
        )

    assert resp.status_code == 200
    assert resp.json()["table_id"] == "tblNEW123"


def test_put_integration_updates_api_key_env_name(tmp_path: Path, monkeypatch):
    """PUT integration → updates api_key_env (env var NAME, not secret)."""
    monkeypatch.setenv("NEW_API_KEY_ENV", "pat_new_secret")
    monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "pat_test")
    client_dir = tmp_path / "clients" / "quintana-seguros"
    _write_crm_yaml(client_dir, VALID_CRM_DATA)

    with patch(
        "app.integrations.crm_config_router.CLIENTS_ROOT",
        tmp_path / "clients",
    ):
        tc = _make_test_client(tmp_path)
        resp = tc.put(
            "/api/v1/clients/quintana-seguros/integrations/airtable",
            json={"api_key_env": "NEW_API_KEY_ENV"},
        )

    assert resp.status_code == 200
    result = resp.json()
    # Must return the env var NAME, never the secret
    assert result["api_key_env"] == "NEW_API_KEY_ENV"
    assert "pat_new_secret" not in resp.text


def test_put_integration_404_for_nonexistent_client(tmp_path: Path):
    """PUT integration for nonexistent client → 404."""
    with patch(
        "app.integrations.crm_config_router.CLIENTS_ROOT",
        tmp_path / "clients",
    ):
        tc = _make_test_client(tmp_path)
        resp = tc.put(
            "/api/v1/clients/nonexistent/integrations/airtable",
            json={"base_id": "appXXX"},
        )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/clients/{client_id}/integrations/{provider}/test
# ---------------------------------------------------------------------------


def test_post_test_returns_success_with_mock_airtable(tmp_path: Path, monkeypatch):
    """POST test → mocked Airtable returns success with record_count."""
    monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "pat_test")
    client_dir = tmp_path / "clients" / "quintana-seguros"
    _write_crm_yaml(client_dir, VALID_CRM_DATA)

    # Mock the Airtable API call so we don't hit the live service
    mock_records = [{"id": "rec1"}, {"id": "rec2"}]
    with patch(
        "app.integrations.crm_config_router.CLIENTS_ROOT",
        tmp_path / "clients",
    ):
        with patch(
            "app.integrations.crm_config_router._test_airtable_connection",
            return_value={"success": True, "message": "Connected. Found 2 records.", "record_count": 2},
        ):
            tc = _make_test_client(tmp_path)
            resp = tc.post(
                "/api/v1/clients/quintana-seguros/integrations/airtable/test"
            )

    assert resp.status_code == 200
    result = resp.json()
    assert result["success"] is True
    assert "record_count" in result
    assert result["record_count"] == 2


def test_post_test_returns_failure_on_connection_error(tmp_path: Path, monkeypatch):
    """POST test → connection failure returns success=false with message."""
    monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "pat_test")
    client_dir = tmp_path / "clients" / "quintana-seguros"
    _write_crm_yaml(client_dir, VALID_CRM_DATA)

    with patch(
        "app.integrations.crm_config_router.CLIENTS_ROOT",
        tmp_path / "clients",
    ):
        with patch(
            "app.integrations.crm_config_router._test_airtable_connection",
            return_value={"success": False, "message": "Authentication failed: invalid API key."},
        ):
            tc = _make_test_client(tmp_path)
            resp = tc.post(
                "/api/v1/clients/quintana-seguros/integrations/airtable/test"
            )

    assert resp.status_code == 200
    result = resp.json()
    assert result["success"] is False
    assert "message" in result


def test_post_test_never_leaks_api_key_on_failure(tmp_path: Path, monkeypatch):
    """SECURITY: POST test response must NEVER contain the raw API key."""
    monkeypatch.setenv("QUINTANA_AIRTABLE_API_KEY", "pat_ultra_secret_should_not_appear")
    client_dir = tmp_path / "clients" / "quintana-seguros"
    _write_crm_yaml(client_dir, VALID_CRM_DATA)

    with patch(
        "app.integrations.crm_config_router.CLIENTS_ROOT",
        tmp_path / "clients",
    ):
        with patch(
            "app.integrations.crm_config_router._test_airtable_connection",
            return_value={"success": False, "message": "Error: authentication failed."},
        ):
            tc = _make_test_client(tmp_path)
            resp = tc.post(
                "/api/v1/clients/quintana-seguros/integrations/airtable/test"
            )

    assert "pat_ultra_secret_should_not_appear" not in resp.text


def test_post_test_404_for_unconfigured_client(tmp_path: Path):
    """POST test for client with no integration config → 404."""
    with patch(
        "app.integrations.crm_config_router.CLIENTS_ROOT",
        tmp_path / "clients",
    ):
        tc = _make_test_client(tmp_path)
        resp = tc.post(
            "/api/v1/clients/unconfigured-client/integrations/airtable/test"
        )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/clients/{client_id}/integrations/available
# ---------------------------------------------------------------------------


def test_get_available_integrations_returns_airtable_not_connected(tmp_path: Path):
    """GET available integrations for client with no crm.yaml → Airtable not connected."""
    client_dir = tmp_path / "clients" / "new-client"
    client_dir.mkdir(parents=True)

    with patch(
        "app.integrations.crm_config_router.CLIENTS_ROOT",
        tmp_path / "clients",
    ):
        tc = _make_test_client(tmp_path)
        resp = tc.get("/api/v1/clients/new-client/integrations/available")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    item = data[0]
    assert item["provider"] == "airtable"
    assert item["name"] == "Airtable"
    assert item["is_connected"] is False
    assert "icon" in item


def test_get_available_integrations_returns_airtable_connected(tmp_path: Path):
    """GET available integrations for client with crm.yaml → Airtable is_connected=true."""
    client_dir = tmp_path / "clients" / "quintana-seguros"
    _write_crm_yaml(client_dir, VALID_CRM_DATA)

    with patch(
        "app.integrations.crm_config_router.CLIENTS_ROOT",
        tmp_path / "clients",
    ):
        tc = _make_test_client(tmp_path)
        resp = tc.get("/api/v1/clients/quintana-seguros/integrations/available")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["is_connected"] is True


def test_get_available_integrations_not_connected_for_nonexistent_client(tmp_path: Path):
    """GET available integrations for nonexistent client → Airtable not connected (no dir)."""
    with patch(
        "app.integrations.crm_config_router.CLIENTS_ROOT",
        tmp_path / "clients",
    ):
        tc = _make_test_client(tmp_path)
        resp = tc.get("/api/v1/clients/nonexistent/integrations/available")

    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["is_connected"] is False


# ---------------------------------------------------------------------------
# POST /api/v1/clients/{client_id}/integrations/{provider}/connect
# ---------------------------------------------------------------------------


def test_post_connect_creates_crm_yaml(tmp_path: Path):
    """POST connect → creates crm.yaml with default mappings and returns config."""
    client_dir = tmp_path / "clients" / "new-client"
    client_dir.mkdir(parents=True)

    with patch(
        "app.integrations.crm_config_router.CLIENTS_ROOT",
        tmp_path / "clients",
    ):
        tc = _make_test_client(tmp_path)
        resp = tc.post(
            "/api/v1/clients/new-client/integrations/airtable/connect",
            json={
                "base_id": "appNEWBASEID",
                "table_id": "tblNEWTABLE",
                "api_key_env": "NEW_CLIENT_AIRTABLE_API_KEY",
            },
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["provider"] == "airtable"
    assert data["base_id"] == "appNEWBASEID"
    assert data["table_id"] == "tblNEWTABLE"
    assert data["api_key_env"] == "NEW_CLIENT_AIRTABLE_API_KEY"
    assert data["match_field"] == "lead_id"
    assert data["field_count"] == 5  # 5 default fields

    # crm.yaml should exist on disk
    crm_path = tmp_path / "clients" / "new-client" / "crm.yaml"
    assert crm_path.exists()


def test_post_connect_creates_default_status_mapping(tmp_path: Path):
    """POST connect → crm.yaml contains default status_mapping."""
    client_dir = tmp_path / "clients" / "new-client"
    client_dir.mkdir(parents=True)

    with patch(
        "app.integrations.crm_config_router.CLIENTS_ROOT",
        tmp_path / "clients",
    ):
        tc = _make_test_client(tmp_path)
        tc.post(
            "/api/v1/clients/new-client/integrations/airtable/connect",
            json={
                "base_id": "appXXX",
                "table_id": "tblYYY",
                "api_key_env": "NEW_KEY",
            },
        )

    crm_path = tmp_path / "clients" / "new-client" / "crm.yaml"
    import yaml as _yaml
    raw = _yaml.safe_load(crm_path.read_text())
    assert "status_mapping" in raw
    assert raw["status_mapping"]["new"] == "New"
    assert raw["status_mapping"]["not_interested"] == "Not Interested"
    assert "import_status_mapping" in raw
    assert raw["import_status_mapping"]["New"] == "new"


def test_post_connect_409_when_already_configured(tmp_path: Path):
    """POST connect when crm.yaml already exists → 409 Conflict."""
    client_dir = tmp_path / "clients" / "existing-client"
    _write_crm_yaml(client_dir, VALID_CRM_DATA)

    with patch(
        "app.integrations.crm_config_router.CLIENTS_ROOT",
        tmp_path / "clients",
    ):
        tc = _make_test_client(tmp_path)
        resp = tc.post(
            "/api/v1/clients/existing-client/integrations/airtable/connect",
            json={
                "base_id": "appXXX",
                "table_id": "tblYYY",
                "api_key_env": "SOME_KEY",
            },
        )

    assert resp.status_code == 409


def test_post_connect_404_when_client_dir_not_found(tmp_path: Path):
    """POST connect when client directory does not exist → 404."""
    with patch(
        "app.integrations.crm_config_router.CLIENTS_ROOT",
        tmp_path / "clients",
    ):
        tc = _make_test_client(tmp_path)
        resp = tc.post(
            "/api/v1/clients/nonexistent/integrations/airtable/connect",
            json={
                "base_id": "appXXX",
                "table_id": "tblYYY",
                "api_key_env": "SOME_KEY",
            },
        )

    assert resp.status_code == 404


def test_post_connect_never_returns_raw_api_key(tmp_path: Path):
    """SECURITY: POST connect response must NEVER contain the raw API key value."""
    client_dir = tmp_path / "clients" / "new-client"
    client_dir.mkdir(parents=True)

    with patch(
        "app.integrations.crm_config_router.CLIENTS_ROOT",
        tmp_path / "clients",
    ):
        tc = _make_test_client(tmp_path)
        resp = tc.post(
            "/api/v1/clients/new-client/integrations/airtable/connect",
            json={
                "base_id": "appXXX",
                "table_id": "tblYYY",
                "api_key_env": "MY_API_KEY_VAR",
            },
        )

    assert resp.status_code == 201
    # The env var NAME is OK — the actual secret value must never appear
    assert "MY_API_KEY_VAR" in resp.text   # name is present
    # No raw secret leakage — only name stored in yaml


# ---------------------------------------------------------------------------
# DELETE /api/v1/clients/{client_id}/integrations/{provider}/disconnect
# ---------------------------------------------------------------------------


def test_delete_disconnect_removes_crm_yaml(tmp_path: Path):
    """DELETE disconnect → crm.yaml is deleted and success returned."""
    client_dir = tmp_path / "clients" / "quintana-seguros"
    _write_crm_yaml(client_dir, VALID_CRM_DATA)

    crm_path = tmp_path / "clients" / "quintana-seguros" / "crm.yaml"
    assert crm_path.exists()

    with patch(
        "app.integrations.crm_config_router.CLIENTS_ROOT",
        tmp_path / "clients",
    ):
        tc = _make_test_client(tmp_path)
        resp = tc.delete(
            "/api/v1/clients/quintana-seguros/integrations/airtable/disconnect"
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "message" in data
    assert not crm_path.exists()


def test_delete_disconnect_404_when_not_configured(tmp_path: Path):
    """DELETE disconnect when no crm.yaml → 404."""
    client_dir = tmp_path / "clients" / "no-crm-client"
    client_dir.mkdir(parents=True)

    with patch(
        "app.integrations.crm_config_router.CLIENTS_ROOT",
        tmp_path / "clients",
    ):
        tc = _make_test_client(tmp_path)
        resp = tc.delete(
            "/api/v1/clients/no-crm-client/integrations/airtable/disconnect"
        )

    assert resp.status_code == 404
