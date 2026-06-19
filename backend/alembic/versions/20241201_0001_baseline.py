"""Baseline migration — captures the complete Qora schema at Phase B foundation.

This migration represents the full schema state as of the Phase B database migration
foundation. It was hand-authored from PRAGMA table_info(*) output on the production
qora.db and validated against all ORM model definitions.

Schema inventory classification:
  active       — Used by at least one core Qora workflow
  compatibility — Present for backward compatibility; deprecated but not provably unused
  candidate-unused — (none identified at this stage)

Notable compatibility columns:
  clients.broker_name — Not in current ORM model; present in actual DB from earlier
                        migration. Classified as compatibility and preserved in baseline.

Revision ID: 20241201_0001
Revises: (none — initial baseline)
Create Date: 2024-12-01
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20241201_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the full Qora schema from scratch.

    Matches the exact column set, types, constraints, and indexes present
    in the production qora.db as of Phase B foundation.
    """
    # ------------------------------------------------------------------
    # clients — tenant/broker configuration
    # Classification: ALL columns active except broker_name (compatibility)
    # ------------------------------------------------------------------
    op.create_table(
        "clients",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        # compatibility: broker_name not in current ORM model but present in DB
        # NOTE: actual qora.db has broker_name NOT NULL (PRAGMA notnull=1) — preserved here
        # server_default="" so ORM inserts (which omit broker_name) satisfy NOT NULL.
        sa.Column("broker_name", sa.String(), nullable=False, server_default=""),
        sa.Column("agent_name", sa.String(), nullable=False, server_default="Jaumpablo"),
        sa.Column("voice_id", sa.String(), nullable=False),
        sa.Column("system_prompt_override", sa.Text(), nullable=True),
        sa.Column("knowledge_base", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("model", sa.String(), nullable=False, server_default="gpt-4o"),
        sa.Column("temperature", sa.Float(), nullable=False, server_default="0.7"),
        sa.Column("max_tokens", sa.Integer(), nullable=False, server_default="300"),
        sa.Column(
            "tools_enabled",
            sa.Text(),
            nullable=False,
            server_default='["get_lead_details","mark_not_interested","schedule_followup"]',
        ),
        sa.Column("scheduler_enabled", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("scheduler_max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column(
            "scheduler_cooldown_minutes", sa.Integer(), nullable=False, server_default="60"
        ),
        sa.Column(
            "scheduler_allowed_hours_start", sa.Integer(), nullable=False, server_default="9"
        ),
        sa.Column(
            "scheduler_allowed_hours_end", sa.Integer(), nullable=False, server_default="20"
        ),
        sa.Column(
            "scheduler_retry_on_outcomes",
            sa.Text(),
            nullable=False,
            server_default='["follow_up","retry_call","schedule_call"]',
        ),
        sa.Column(
            "scheduler_timezone",
            sa.String(),
            nullable=False,
            server_default="America/Argentina/Buenos_Aires",
        ),
        sa.Column("next_action_max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column(
            "next_action_min_interest_for_followup",
            sa.Integer(),
            nullable=False,
            server_default="40",
        ),
        sa.Column(
            "next_action_close_on_hard_rejection",
            sa.Boolean(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "analysis_language", sa.String(), nullable=False, server_default="Spanish"
        ),
        sa.Column("extraction_config", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # ------------------------------------------------------------------
    # agents — per-client AI agent configuration
    # Classification: ALL columns active
    # ------------------------------------------------------------------
    op.create_table(
        "agents",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("voice_id", sa.String(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("knowledge_base", sa.Text(), nullable=True),
        sa.Column("model", sa.String(), nullable=False, server_default="gpt-4o"),
        sa.Column("temperature", sa.Float(), nullable=False, server_default="0.7"),
        sa.Column("max_tokens", sa.Integer(), nullable=False, server_default="300"),
        sa.Column(
            "tools_enabled",
            sa.Text(),
            nullable=False,
            server_default='["get_lead_details","mark_not_interested","schedule_followup"]',
        ),
        sa.Column("elevenlabs_agent_id", sa.String(), nullable=True),
        sa.Column("tool_config", sa.Text(), nullable=True),
        sa.Column("tts_speed", sa.Float(), nullable=False, server_default="0.95"),
        sa.Column("tts_stability", sa.Float(), nullable=False, server_default="0.4"),
        sa.Column("tts_similarity_boost", sa.Float(), nullable=False, server_default="0.75"),
        sa.Column(
            "tts_model", sa.Text(), nullable=False, server_default="eleven_flash_v2_5"
        ),
        sa.Column("soft_timeout_seconds", sa.Float(), nullable=True),
        sa.Column("soft_timeout_message", sa.Text(), nullable=True),
        sa.Column("soft_timeout_use_llm", sa.Integer(), nullable=True),
        sa.Column("elevenlabs_sync_status", sa.Text(), nullable=True),
        sa.Column("elevenlabs_last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", "slug", name="uq_agents_client_slug"),
    )
    op.create_index("ix_agents_client_id", "agents", ["client_id"])

    # ------------------------------------------------------------------
    # leads — CRM contact records
    # Classification: ALL columns active
    # ------------------------------------------------------------------
    op.create_table(
        "leads",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("phone", sa.String(), nullable=False),
        sa.Column("car_make", sa.String(), nullable=True),
        sa.Column("car_model", sa.String(), nullable=True),
        sa.Column("car_year", sa.Integer(), nullable=True),
        sa.Column("current_insurance", sa.String(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=14),
            nullable=False,
            server_default="new",
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("call_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_called_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column("zona", sa.Text(), nullable=True),
        sa.Column("summary_last_call", sa.Text(), nullable=True),
        sa.Column("objections_heard", sa.JSON(), nullable=True),
        sa.Column("interest_level", sa.Integer(), nullable=True),
        sa.Column("extracted_facts", sa.JSON(), nullable=True),
        sa.Column("do_not_call", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("next_action", sa.String(), nullable=True),
        sa.Column("next_action_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_crm_id", sa.Text(), nullable=True),
        sa.Column("external_lead_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_leads_client_id", "leads", ["client_id"])

    # ------------------------------------------------------------------
    # call_sessions — ElevenLabs call records
    # Classification: ALL columns active
    # ------------------------------------------------------------------
    op.create_table(
        "call_sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("lead_id", sa.String(), sa.ForeignKey("leads.id"), nullable=True),
        sa.Column("elevenlabs_conversation_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="initiated"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("billable_minutes", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("closed_reason", sa.String(), nullable=True),
        sa.Column("total_user_turns", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_agent_turns", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("extracted_facts", sa.JSON(), nullable=True),
        sa.Column("merged_into_session_id", sa.String(), nullable=True),
        sa.Column("agent_id", sa.String(), sa.ForeignKey("agents.id"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_call_sessions_client_id", "call_sessions", ["client_id"])
    op.create_index("ix_call_sessions_lead_id", "call_sessions", ["lead_id"])

    # ------------------------------------------------------------------
    # transcript_turns — per-turn call transcript
    # Classification: ALL columns active
    # ------------------------------------------------------------------
    op.create_table(
        "transcript_turns",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column(
            "session_id", sa.String(), sa.ForeignKey("call_sessions.id"), nullable=False
        ),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("filler_detected", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_transcript_turns_session_id", "transcript_turns", ["session_id"])

    # ------------------------------------------------------------------
    # call_analyses — structured analysis of each call (1:1 with call_sessions)
    # Classification: ALL columns active; abandonment_reason is compatibility
    # ------------------------------------------------------------------
    op.create_table(
        "call_analyses",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column(
            "session_id",
            sa.String(),
            sa.ForeignKey("call_sessions.id"),
            nullable=False,
        ),
        sa.Column("lead_id", sa.String(), sa.ForeignKey("leads.id"), nullable=True),
        sa.Column("client_id", sa.String(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("interest_level", sa.Integer(), nullable=True),
        sa.Column("classification", sa.String(), nullable=True),
        sa.Column("outcome_reason", sa.String(), nullable=True),
        sa.Column("urgency", sa.String(), nullable=True),
        sa.Column("primary_need", sa.Text(), nullable=True),
        sa.Column("next_action_suggested", sa.String(), nullable=True),
        sa.Column("current_insurance", sa.String(), nullable=True),
        sa.Column("data_corrections", sa.Text(), nullable=False, server_default=""),
        sa.Column("misc_notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("objections", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("products", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("specific_needs", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("buying_signals", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("pain_points", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("service_issues", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("profile_facts", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("commitment_signals", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("primary_objection_category", sa.String(), nullable=True),
        sa.Column("primary_pain_category", sa.String(), nullable=True),
        sa.Column("objections_count", sa.Integer(), nullable=True),
        sa.Column("pain_points_count", sa.Integer(), nullable=True),
        sa.Column("service_issues_count", sa.Integer(), nullable=True),
        # compatibility: abandonment_reason deprecated; receives NULL going forward
        sa.Column("abandonment_reason", sa.Text(), nullable=True),
        sa.Column("was_abrupt", sa.Boolean(), nullable=True),
        sa.Column("abandonment_trigger", sa.String(), nullable=True),
        sa.Column("extra_axes_data", sa.Text(), nullable=True),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("analysis_status", sa.String(), nullable=False, server_default="ok"),
        sa.Column("analysis_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id"),
    )
    op.create_index(
        "ix_call_analyses_classification", "call_analyses", ["classification"]
    )
    op.create_index("ix_call_analyses_client_id", "call_analyses", ["client_id"])
    op.create_index("ix_call_analyses_lead_id", "call_analyses", ["lead_id"])
    # Present in production qora.db — must be in baseline for zero-drift guarantee
    op.create_index("ix_call_analyses_session_id", "call_analyses", ["session_id"])
    op.create_index(
        "ix_ca_primary_objection_category",
        "call_analyses",
        ["primary_objection_category"],
    )
    op.create_index(
        "ix_ca_primary_pain_category", "call_analyses", ["primary_pain_category"]
    )

    # ------------------------------------------------------------------
    # lead_profile_facts — key-value store for lead facts (append-supersede)
    # Classification: ALL columns active
    # ------------------------------------------------------------------
    op.create_table(
        "lead_profile_facts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("lead_id", sa.String(), sa.ForeignKey("leads.id"), nullable=False),
        sa.Column("fact_key", sa.String(), nullable=False),
        sa.Column("fact_value", sa.Text(), nullable=False),
        sa.Column("source_call_id", sa.String(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_lead_profile_facts_lead_key_active",
        "lead_profile_facts",
        ["lead_id", "fact_key", "superseded_at"],
    )
    op.create_index(
        "ix_lead_profile_facts_lead_id", "lead_profile_facts", ["lead_id"]
    )
    op.create_index(
        "ix_lead_profile_facts_source_call_id",
        "lead_profile_facts",
        ["source_call_id"],
    )

    # ------------------------------------------------------------------
    # lead_custom_fields — type-enforced key-value store for business data
    # Classification: ALL columns active
    # ------------------------------------------------------------------
    op.create_table(
        "lead_custom_fields",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("lead_id", sa.String(), sa.ForeignKey("leads.id"), nullable=False),
        sa.Column("client_id", sa.String(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("field_key", sa.String(), nullable=False),
        sa.Column("field_value", sa.Text(), nullable=True),
        sa.Column("field_type", sa.String(), nullable=False, server_default="string"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lcf_lead_client", "lead_custom_fields", ["lead_id", "client_id"])
    op.create_index(
        "ix_lcf_lead_client_key",
        "lead_custom_fields",
        ["lead_id", "client_id", "field_key"],
        unique=True,
    )

    # ------------------------------------------------------------------
    # lead_interest_history — time series of interest scores per lead
    # Classification: ALL columns active
    # ------------------------------------------------------------------
    op.create_table(
        "lead_interest_history",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("lead_id", sa.String(), sa.ForeignKey("leads.id"), nullable=False),
        sa.Column("interest_level", sa.Integer(), nullable=False),
        sa.Column("source_call_id", sa.String(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_lead_interest_history_lead_id", "lead_interest_history", ["lead_id"]
    )
    op.create_index(
        "ix_lead_interest_history_lead_recorded_at",
        "lead_interest_history",
        ["lead_id", "recorded_at"],
    )

    # ------------------------------------------------------------------
    # scheduled_calls — outbound call queue (Phase 6)
    # Classification: ALL columns active
    # ------------------------------------------------------------------
    op.create_table(
        "scheduled_calls",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("lead_id", sa.String(), sa.ForeignKey("leads.id"), nullable=False),
        sa.Column("source_session_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("trigger_reason", sa.String(), nullable=False),
        sa.Column("outcome_session_id", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("agent_id", sa.String(), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scheduled_calls_client_id", "scheduled_calls", ["client_id"])
    op.create_index("ix_scheduled_calls_lead_id", "scheduled_calls", ["lead_id"])
    op.create_index(
        "ix_scheduled_calls_lead_status", "scheduled_calls", ["lead_id", "status"]
    )
    op.create_index(
        "ix_scheduled_calls_status_scheduled_at",
        "scheduled_calls",
        ["status", "scheduled_at"],
    )


def downgrade() -> None:
    """Drop all Qora tables in reverse dependency order."""
    op.drop_table("scheduled_calls")
    op.drop_table("lead_interest_history")
    op.drop_table("lead_custom_fields")
    op.drop_table("lead_profile_facts")
    op.drop_table("call_analyses")
    op.drop_table("transcript_turns")
    op.drop_table("call_sessions")
    op.drop_table("leads")
    op.drop_table("agents")
    op.drop_table("clients")
