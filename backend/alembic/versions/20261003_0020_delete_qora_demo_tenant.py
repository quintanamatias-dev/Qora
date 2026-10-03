"""One-time data migration: hard-delete every row of the removed Qora demo tenant.

The Qora demo agent, public demo page, and global agent defaults were removed
in commit 868049a (chore/remove-qora-demo). This migration deletes every
database row that still references client_id = 'qora-demo': the demo client
itself, its agent(s), every config revision, every lead and its derived rows,
every call session and its derived rows, and any scheduled calls.

Deletes run in FK-safe child-before-parent order. agents.active_revision_id
and clients.active_config_revision_id point INTO the revision tables, so both
pointers are nulled before their target revisions are deleted.

Tables are probed with inspect() and skipped if absent — this migration must
stay runnable against any DB state at this revision without assuming every
optional/future table exists.

Idempotent: re-running upgrade() against a DB with no qora-demo rows left
deletes 0 rows from every table.

Rollback plan: NONE. downgrade() is a deliberate no-op — see its docstring.

Revision ID: 20261003_0020
Revises: 20261003_0019
Create Date: 2026-10-03
"""

from __future__ import annotations

import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "20261003_0020"
down_revision: Union[str, None] = "20261003_0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

_QORA_DEMO_CLIENT_ID = "qora-demo"


def _delete(bind, existing_tables: set[str], table: str, sql: str, params: dict) -> None:
    """Run one DELETE/UPDATE statement if its table exists; log the row count."""
    if table not in existing_tables:
        logger.info("delete_qora_demo_tenant: table %s absent, skipped", table)
        return
    result = bind.execute(sa.text(sql), params)
    logger.info("delete_qora_demo_tenant: %s affected %s row(s)", table, result.rowcount)


def upgrade() -> None:
    """Hard-delete every row belonging to the qora-demo tenant, FK-safe order."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    cid = {"cid": _QORA_DEMO_CLIENT_ID}

    # 1. transcript_turns — child of call_sessions
    _delete(
        bind,
        existing_tables,
        "transcript_turns",
        "DELETE FROM transcript_turns WHERE session_id IN "
        "(SELECT id FROM call_sessions WHERE client_id = :cid)",
        cid,
    )

    # 2. call_analyses — references client_id directly and call_sessions
    _delete(
        bind,
        existing_tables,
        "call_analyses",
        "DELETE FROM call_analyses WHERE client_id = :cid OR session_id IN "
        "(SELECT id FROM call_sessions WHERE client_id = :cid)",
        cid,
    )

    # 3. lead_profile_facts — references leads and (nullable) call_sessions
    _delete(
        bind,
        existing_tables,
        "lead_profile_facts",
        "DELETE FROM lead_profile_facts WHERE lead_id IN "
        "(SELECT id FROM leads WHERE client_id = :cid) OR source_call_id IN "
        "(SELECT id FROM call_sessions WHERE client_id = :cid)",
        cid,
    )

    # 4. lead_interest_history — references leads and (nullable) call_sessions
    _delete(
        bind,
        existing_tables,
        "lead_interest_history",
        "DELETE FROM lead_interest_history WHERE lead_id IN "
        "(SELECT id FROM leads WHERE client_id = :cid) OR source_call_id IN "
        "(SELECT id FROM call_sessions WHERE client_id = :cid)",
        cid,
    )

    # 5. lead_custom_fields — references client_id directly
    _delete(
        bind,
        existing_tables,
        "lead_custom_fields",
        "DELETE FROM lead_custom_fields WHERE client_id = :cid",
        cid,
    )

    # 6. scheduled_calls — references client_id directly
    _delete(
        bind,
        existing_tables,
        "scheduled_calls",
        "DELETE FROM scheduled_calls WHERE client_id = :cid",
        cid,
    )

    # 7. call_sessions — references client_id directly
    _delete(
        bind,
        existing_tables,
        "call_sessions",
        "DELETE FROM call_sessions WHERE client_id = :cid",
        cid,
    )

    # 8. leads — references client_id directly
    _delete(bind, existing_tables, "leads", "DELETE FROM leads WHERE client_id = :cid", cid)

    # 9. Null agents.active_revision_id before deleting agent_config_revisions
    _delete(
        bind,
        existing_tables,
        "agents",
        "UPDATE agents SET active_revision_id = NULL WHERE client_id = :cid",
        cid,
    )

    # 10. agent_config_revisions — references agents
    _delete(
        bind,
        existing_tables,
        "agent_config_revisions",
        "DELETE FROM agent_config_revisions WHERE agent_id IN "
        "(SELECT id FROM agents WHERE client_id = :cid)",
        cid,
    )

    # 11. agents — references client_id directly
    _delete(bind, existing_tables, "agents", "DELETE FROM agents WHERE client_id = :cid", cid)

    # 12. Null clients.active_config_revision_id before deleting client_config_revisions
    _delete(
        bind,
        existing_tables,
        "clients",
        "UPDATE clients SET active_config_revision_id = NULL WHERE id = :cid",
        cid,
    )

    # 13. client_config_revisions — references client_id directly
    _delete(
        bind,
        existing_tables,
        "client_config_revisions",
        "DELETE FROM client_config_revisions WHERE client_id = :cid",
        cid,
    )

    # 14. clients — the tenant row itself
    _delete(bind, existing_tables, "clients", "DELETE FROM clients WHERE id = :cid", cid)


def downgrade() -> None:
    """No-op: this is an irreversible hard data deletion.

    The qora-demo tenant and every row that referenced it were permanently
    removed by upgrade(). There is no data to restore — the rows, including
    their original timestamps and content, no longer exist anywhere in this
    migration chain. A real rollback would require restoring from a backup
    taken before upgrade() ran, not an Alembic downgrade.
    """
    pass
