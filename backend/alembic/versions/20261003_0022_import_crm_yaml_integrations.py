"""One-time import: client_integrations rows from existing crm.yaml files (P3-D6).

Reads every backend/clients/*/crm.yaml and inserts a matching
client_integrations row containing only the NON-SECRET fields (base_id,
table_id, match_field, field_mappings, custom_fields, quote_ready_fields,
status_mapping, import_status_mapping, enabled). The legacy env var name a
client's crm.yaml referenced for its API key (api_key / api_key_env) is
recorded in config.legacy_env_var_name so the runtime secret resolution
order (DB -> env, P3-D3) can fall back to it — the literal credential VALUE
is never read or stored here.

This migration deliberately does NOT import any `app.*` module (house
pattern, same as 20261002_0015/20261003_0018): yaml is parsed inline.

A client directory with no crm.yaml gets no row. A crm.yaml referencing a
client_id with no matching `clients` row is skipped (FK-safe, logged) rather
than failing the whole migration.

Idempotent: re-running upgrade() does not duplicate an existing
(client_id, provider) row — INSERT OR IGNORE on the table's unique
constraint.

Design: openspec/changes/client-integrations-secrets/design.md P3-D6.

Revision ID: 20261003_0022
Revises: 20261003_0021
Create Date: 2026-10-03
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
import yaml
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "20261003_0022"
down_revision: Union[str, None] = "20261003_0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

# backend/clients — module-level so tests can monkeypatch it to a tmp dir.
_CLIENTS_ROOT = Path(__file__).resolve().parent.parent.parent / "clients"

# Mirrors CRMConfig.resolve_api_key's heuristic (app/integrations/crm_config.py) —
# duplicated here deliberately: migrations never import app.* (house pattern).
_ENV_VAR_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]+$")

_NON_SECRET_KEYS = (
    "base_id",
    "table_id",
    "match_field",
    "field_mappings",
    "custom_fields",
    "quote_ready_fields",
    "status_mapping",
    "import_status_mapping",
)


def _legacy_env_var_name(raw: dict) -> str | None:
    """Return the legacy env var name this crm.yaml's api_key referenced, if any."""
    api_key_value = raw.get("api_key_env") or raw.get("api_key")
    if isinstance(api_key_value, str) and _ENV_VAR_NAME_PATTERN.match(api_key_value):
        return api_key_value
    return None


def _build_config(raw: dict) -> dict:
    """Non-secret fields only — never api_key/api_key_env's literal value."""
    config = {key: raw.get(key) for key in _NON_SECRET_KEYS if key in raw}
    legacy_env_var_name = _legacy_env_var_name(raw)
    if legacy_env_var_name:
        config["legacy_env_var_name"] = legacy_env_var_name
    return config


def upgrade() -> None:
    """Import every backend/clients/*/crm.yaml's non-secret fields."""
    bind = op.get_bind()
    existing_client_ids = {
        row[0] for row in bind.execute(sa.text("SELECT id FROM clients")).fetchall()
    }

    if not _CLIENTS_ROOT.exists():
        logger.info("import_crm_yaml_integrations: clients root %s absent, skipped", _CLIENTS_ROOT)
        return

    now = datetime.now(timezone.utc)
    for crm_yaml_path in sorted(_CLIENTS_ROOT.glob("*/crm.yaml")):
        client_id = crm_yaml_path.parent.name

        if client_id not in existing_client_ids:
            logger.info(
                "import_crm_yaml_integrations: no clients row for %r, skipped", client_id
            )
            continue

        try:
            raw = yaml.safe_load(crm_yaml_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            logger.error(
                "import_crm_yaml_integrations: malformed crm.yaml for %r: %s", client_id, exc
            )
            continue

        if not isinstance(raw, dict):
            logger.error(
                "import_crm_yaml_integrations: invalid crm.yaml for %r (not a mapping)",
                client_id,
            )
            continue

        provider = raw.get("provider") or raw.get("adapter") or "airtable"
        enabled = bool(raw.get("enabled", True))
        config = _build_config(raw)

        bind.execute(
            sa.text(
                "INSERT OR IGNORE INTO client_integrations "
                "(id, client_id, provider, enabled, config, status, status_reason, "
                "last_checked_at, created_at, created_by, updated_at, updated_by) "
                "VALUES (:id, :client_id, :provider, :enabled, :config, 'ok', NULL, "
                "NULL, :now, 'system', :now, 'system')"
            ),
            {
                "id": str(uuid.uuid4()),
                "client_id": client_id,
                "provider": provider,
                "enabled": enabled,
                "config": json.dumps(config),
                "now": now,
            },
        )
        logger.info(
            "import_crm_yaml_integrations: imported %r provider=%r from crm.yaml",
            client_id,
            provider,
        )


def downgrade() -> None:
    """Delete every client_integrations row with source metadata matching this import.

    Rows are not individually tagged with a migration source, so downgrade
    removes every row that still has status='ok', status_reason=NULL, and
    created_by='system' — the exact shape this migration inserts. A row
    later edited through the API (which always sets created_by to the
    operator, or recomputes status) is left untouched.
    """
    op.execute(
        "DELETE FROM client_integrations "
        "WHERE created_by = 'system' AND updated_by = 'system' "
        "AND status = 'ok' AND status_reason IS NULL"
    )
