"""Regression guard: webhook.py must not read DEPRECATED Client columns.

The `Client.system_prompt_override` / `Client.tools_enabled` columns are
DEPRECATED (Phase 7 migration) and are vestigial fallback reads for an
`agent is None` state that no live call can reach since 1a. The columns
themselves stay on the model (drop deferred); only the dead reads are removed.

Spec: openspec/changes/elevenlabs-reconciler/tasks.md — Phase 5 (5.1, 5.2);
design.md R-D3.
"""

from __future__ import annotations

from pathlib import Path

_WEBHOOK_SOURCE = (
    Path(__file__).resolve().parents[3] / "app" / "voice" / "webhook.py"
).read_text()


def test_no_remaining_system_prompt_override_read_in_webhook():
    assert "client_orm.system_prompt_override" not in _WEBHOOK_SOURCE


def test_no_remaining_tools_enabled_fallback_read_when_agent_is_none():
    assert "client_orm.tools_enabled" not in _WEBHOOK_SOURCE


def test_has_static_prompt_legacy_branch_removed():
    assert (
        "agent is None and client_orm is not None and client_orm.system_prompt_override"
        not in _WEBHOOK_SOURCE
    )
