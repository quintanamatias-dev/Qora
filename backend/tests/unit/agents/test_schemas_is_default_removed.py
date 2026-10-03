"""Regression guard: AgentResponse no longer exposes is_default.

The Agent.is_default column stays on the model (drop deferred); only the
schema-level exposure and its write-time uniqueness enforcement are removed,
since resolve_single_active_agent() never reads is_default (design.md R-D3).

Spec: openspec/changes/elevenlabs-reconciler/tasks.md — Phase 6 (6.2).
"""

from __future__ import annotations


def test_agent_response_schema_no_longer_exposes_is_default():
    from app.agents.schemas import AgentResponse

    assert "is_default" not in AgentResponse.model_fields
