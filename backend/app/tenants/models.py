"""QORA Tenants — SQLAlchemy models for Client configuration and Agent entity.

Based on the design.md schema for the `clients` and `agents` tables.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid4() -> str:
    return str(uuid.uuid4())


class Agent(Base):
    """First-class Agent entity — one Client may have N Agents.

    Exactly one Agent per client has is_default=True (enforced at application layer).
    """

    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid4)
    client_id: Mapped[str] = mapped_column(
        String, ForeignKey("clients.id"), nullable=False, index=True
    )
    slug: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    voice_id: Mapped[str] = mapped_column(String, nullable=False)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    knowledge_base: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None
    )
    model: Mapped[str] = mapped_column(String, nullable=False, default="gpt-4.1-mini")
    temperature: Mapped[float] = mapped_column(nullable=False, default=0.7)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    tools_enabled: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default='["get_lead_details"]',
    )
    elevenlabs_agent_id: Mapped[str | None] = mapped_column(
        String, nullable=True, default=None
    )
    # Per-agent tool configuration — JSON stored as TEXT (nullable).
    # Used by capture_data to store the OpenAI function-calling parameters schema.
    # NULL means no configurable tools are configured for this agent.
    # Example: {"capture_data": {"type": "object", "properties": {...}, "required": [...]}}
    tool_config: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # TTS runtime config — per-agent ElevenLabs voice synthesis parameters
    # Defaults match Settings.elevenlabs_speed/stability/similarity_boost
    tts_speed: Mapped[float] = mapped_column(Float, nullable=False, default=0.95)
    tts_stability: Mapped[float] = mapped_column(Float, nullable=False, default=0.4)
    tts_similarity_boost: Mapped[float] = mapped_column(Float, nullable=False, default=0.75)
    # ElevenLabs TTS model — determines voice synthesis capabilities.
    # "eleven_flash_v2_5" (default): low-latency, supports speed/stability/similarity_boost.
    # "eleven_v3_conversational": expressive tags ([laughs], [slow], etc.), NO speed/stability/similarity_boost.
    tts_model: Mapped[str] = mapped_column(String, nullable=False, default="eleven_v4_turbo")
    # ElevenLabs soft timeout configuration (sdd/elevenlabs-provisioning)
    # NULL = use ElevenLabs dashboard defaults — no PATCH is sent.
    # soft_timeout_use_llm stored as BOOLEAN (SQLAlchemy maps to INTEGER 0/1 in SQLite)
    soft_timeout_seconds: Mapped[float | None] = mapped_column(
        Float, nullable=True, default=None
    )
    soft_timeout_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None
    )
    soft_timeout_use_llm: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, default=None
    )
    # C2: ElevenLabs phone number resource ID for SIP trunk outbound-call API.
    # Seeded from ELEVENLABS_PHONE_NUMBER_ID env var during initial setup.
    # Configurable via PATCH /agents/{agent_id}.
    # NULL on pre-C2 rows — not required for inbound-only agents.
    elevenlabs_phone_number_id: Mapped[str | None] = mapped_column(
        String, nullable=True, default=None
    )
    # ElevenLabs agent config sync — sdd/elevenlabs-config
    # NULL = skip that config block in the unified PATCH payload (preserve dashboard settings).
    voicemail_detection_enabled: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, default=None
    )
    max_call_duration_seconds: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
    # ElevenLabs sync tracking columns
    elevenlabs_sync_status: Mapped[str | None] = mapped_column(
        String, nullable=True, default=None
    )
    elevenlabs_last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    # agent-config-revisions-routing (D4): single pointer to this agent's active
    # AgentConfigRevision. NULL until the import migration (or a seeder) activates one.
    active_revision_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("agent_config_revisions.id"),
        nullable=True,
        default=None,
    )
    # agent-config-inheritance (D19): STANDARD_VERSION active when this agent's
    # Agent.* columns were last derived by materialize_agent_config(). NULL until
    # the agent has been materialized by a 1b write/propagation path.
    materialized_standard_version: Mapped[str | None] = mapped_column(
        String, nullable=True, default=None
    )

    __table_args__ = (
        # Enforce that slug is unique per client (not globally)
        UniqueConstraint("client_id", "slug", name="uq_agents_client_slug"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Agent id={self.id!r} slug={self.slug!r} client={self.client_id!r}>"


class AgentConfigRevision(Base):
    """Immutable, versioned agent configuration snapshot (design.md D4).

    Rows are insert-only: no UPDATE or DELETE path exists anywhere in the
    service layer. revision_number is monotonically increasing per agent_id,
    starting at 1. source distinguishes how the revision was created.
    """

    __tablename__ = "agent_config_revisions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid4)
    agent_id: Mapped[str] = mapped_column(
        String, ForeignKey("agents.id"), nullable=False, index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # AgentConfigV1-shaped JSON payload, stored as TEXT (same pattern as
    # Agent.tools_enabled / Client.entitlement_overrides elsewhere in this module).
    config: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[str] = mapped_column(String, nullable=False, default="v1")
    # One of: "import", "api", "rollback".
    source: Mapped[str] = mapped_column(String, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # Outcome of the ElevenLabs projection sync triggered when this revision was
    # activated (design.md D7): one of "synced", "drift", "error", "skipped", or
    # NULL when no sync was attempted (e.g. imported revisions).
    elevenlabs_sync_status: Mapped[str | None] = mapped_column(
        String, nullable=True, default=None
    )

    __table_args__ = (
        UniqueConstraint(
            "agent_id", "revision_number", name="uq_agent_config_revisions_agent_number"
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<AgentConfigRevision id={self.id!r} agent_id={self.agent_id!r} "
            f"revision_number={self.revision_number!r} source={self.source!r}>"
        )


class ClientConfigRevision(Base):
    """Immutable, versioned client-level configuration overrides (design.md D11).

    Rows are insert-only: no UPDATE or DELETE path exists anywhere in the
    service layer. revision_number is monotonically increasing per client_id,
    starting at 1. config stores sparse overrides only (ClientConfigV1-shaped
    JSON) — fields the client has actually set, not a full copy of the
    AgentConfigStandard.
    """

    __tablename__ = "client_config_revisions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid4)
    client_id: Mapped[str] = mapped_column(
        String, ForeignKey("clients.id"), nullable=False, index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # ClientConfigV1-shaped sparse JSON payload, stored as TEXT (same pattern
    # as AgentConfigRevision.config).
    config: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[str] = mapped_column(String, nullable=False, default="v1")
    # One of: "import", "api", "rollback".
    source: Mapped[str] = mapped_column(String, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)

    __table_args__ = (
        UniqueConstraint(
            "client_id",
            "revision_number",
            name="uq_client_config_revisions_client_number",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<ClientConfigRevision id={self.id!r} client_id={self.client_id!r} "
            f"revision_number={self.revision_number!r} source={self.source!r}>"
        )


class ClientAnalysisProfileRevision(Base):
    """Immutable, versioned per-client analysis profile snapshot (design.md P5-D2).

    Rows are insert-only: no UPDATE or DELETE path exists anywhere in the
    service layer. revision_number is monotonically increasing per client_id,
    starting at 1. config is a FULL AnalysisProfileConfigV1-shaped JSON
    snapshot (products + need_tags) — not a sparse override set, since the
    analysis profile has no "inherit from elsewhere" concept to be sparse
    against (mirrors AgentConfigRevision's full-snapshot pattern).
    """

    __tablename__ = "client_analysis_profile_revisions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid4)
    client_id: Mapped[str] = mapped_column(
        String, ForeignKey("clients.id"), nullable=False, index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # AnalysisProfileConfigV1-shaped JSON payload, stored as TEXT (same
    # pattern as AgentConfigRevision.config / ClientConfigRevision.config).
    config: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[str] = mapped_column(String, nullable=False, default="1")
    # One of: "import", "api", "rollback".
    source: Mapped[str] = mapped_column(String, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)

    __table_args__ = (
        UniqueConstraint(
            "client_id",
            "revision_number",
            name="uq_client_analysis_profile_revisions_client_number",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<ClientAnalysisProfileRevision id={self.id!r} client_id={self.client_id!r} "
            f"revision_number={self.revision_number!r} source={self.source!r}>"
        )


class SkillPackage(Base):
    """A named collection of skills owned by Qora or by one client (skill-packages, P4-D1).

    Exactly one row has owner_type="qora" (client_id NULL) — the Qora-wide
    default package. Every client that has skills gets its own
    owner_type="client" row, scoped by client_id.
    """

    __tablename__ = "skill_packages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid4)
    owner_type: Mapped[str] = mapped_column(String, nullable=False)  # "qora" | "client"
    client_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("clients.id"), nullable=True, index=True, default=None
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<SkillPackage id={self.id!r} owner_type={self.owner_type!r} "
            f"client_id={self.client_id!r}>"
        )


class Skill(Base):
    """A named slot within a SkillPackage, scoped to a general or agent section
    (skill-packages, P4-D1).

    unique(package_id, slug, agent_id) allows the same slug to exist once as a
    general-section skill and once per agent-section skill within one package.
    active_revision_id is non-null once the skill has at least one revision —
    NULL only transiently between row creation and its first SkillRevision insert.
    """

    __tablename__ = "skills"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid4)
    package_id: Mapped[str] = mapped_column(
        String, ForeignKey("skill_packages.id"), nullable=False, index=True
    )
    slug: Mapped[str] = mapped_column(String, nullable=False)
    section: Mapped[str] = mapped_column(String, nullable=False)  # "general" | "agent"
    agent_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("agents.id"), nullable=True, index=True, default=None
    )
    active_revision_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("skill_revisions.id"), nullable=True, default=None
    )

    __table_args__ = (
        UniqueConstraint("package_id", "slug", "agent_id", name="uq_skills_package_slug_agent"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Skill id={self.id!r} slug={self.slug!r} section={self.section!r}>"


class SkillRevision(Base):
    """Immutable, versioned skill content (skill-packages, P4-D1).

    Rows are insert-only: no UPDATE or DELETE path exists anywhere in the
    service layer. revision_number is monotonically increasing per skill_id,
    starting at 1. Fields mirror SkillRegistryEntry plus content_md — the
    full markdown body a load_skill tool call returns.
    """

    __tablename__ = "skill_revisions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid4)
    skill_id: Mapped[str] = mapped_column(
        String, ForeignKey("skills.id"), nullable=False, index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    filler_text: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_hint: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # One of: "import", "api", "rollback".
    source: Mapped[str] = mapped_column(String, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)

    __table_args__ = (
        UniqueConstraint("skill_id", "revision_number", name="uq_skill_revisions_skill_number"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<SkillRevision id={self.id!r} skill_id={self.skill_id!r} "
            f"revision_number={self.revision_number!r} source={self.source!r}>"
        )


class ClientIntegration(Base):
    """Per-client, non-secret CRM integration config (client-integrations-secrets, P3-D1).

    Mutated in place — no revision history (design.md P3-D1 rationale: config
    edits are rare, low-blast-radius single-value changes). status/status_reason
    are computed by boot validation and recomputed on every config/secret write.
    No secret value is ever stored in `config` — see ClientSecret below.
    """

    __tablename__ = "client_integrations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid4)
    client_id: Mapped[str] = mapped_column(
        String, ForeignKey("clients.id"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # JSON (stored as Text): base_id, table_id, match_field, field_mappings,
    # custom_fields, quote_ready_fields, status_mapping, import_status_mapping,
    # legacy_env_var_name — non-secret fields only.
    config: Mapped[str] = mapped_column(Text, nullable=False)
    # One of "ok" | "degraded" | "disabled".
    status: Mapped[str] = mapped_column(String, nullable=False, default="ok")
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_by: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint("client_id", "provider", name="uq_client_integrations_client_provider"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<ClientIntegration id={self.id!r} client_id={self.client_id!r} "
            f"provider={self.provider!r} status={self.status!r}>"
        )


class ClientSecret(Base):
    """Encrypted per-client secret (client-integrations-secrets, P3-D2).

    ciphertext is produced by app.core.crypto.SecretCrypto — never a plaintext
    value. Mutated in place — no revision history (design.md P3-D1).
    """

    __tablename__ = "client_secrets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid4)
    client_id: Mapped[str] = mapped_column(
        String, ForeignKey("clients.id"), nullable=False, index=True
    )
    integration_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("client_integrations.id"), nullable=True, default=None
    )
    # e.g. "airtable_api_key".
    name: Mapped[str] = mapped_column(String, nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # Fingerprint of the master key that encrypted this row (rotation auditing).
    key_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_by: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint("client_id", "name", name="uq_client_secrets_client_name"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ClientSecret id={self.id!r} client_id={self.client_id!r} name={self.name!r}>"


class Client(Base):
    """Represents a tenant/broker that uses QORA."

    One client == one insurance broker (e.g., Quintana Seguros).
    id is a human-readable slug: "quintana-seguros".
    """

    __tablename__ = "clients"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    agent_name: Mapped[str] = mapped_column(String, nullable=False, default="Jaumpablo")
    voice_id: Mapped[str] = mapped_column(String, nullable=False)
    system_prompt_override: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None
    )
    knowledge_base: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # GPT-4o config (flat on client for simplicity in Phase 0)
    model: Mapped[str] = mapped_column(String, nullable=False, default="gpt-4o")
    temperature: Mapped[float] = mapped_column(nullable=False, default=0.7)
    max_tokens: Mapped[int] = mapped_column(nullable=False, default=300)
    tools_enabled: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default='["get_lead_details","mark_not_interested","schedule_followup"]',
    )

    # ---------------------------------------------------------------------------
    # Scheduler configuration (Phase 6 — flat columns, matches existing pattern)
    # ---------------------------------------------------------------------------

    scheduler_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    scheduler_max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3
    )
    scheduler_cooldown_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60
    )
    scheduler_allowed_hours_start: Mapped[int] = mapped_column(
        Integer, nullable=False, default=9
    )
    scheduler_allowed_hours_end: Mapped[int] = mapped_column(
        Integer, nullable=False, default=20
    )
    scheduler_retry_on_outcomes: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default='["follow_up","retry_call","schedule_call"]',
    )
    scheduler_timezone: Mapped[str] = mapped_column(
        String, nullable=False, default="America/Argentina/Buenos_Aires"
    )
    # C6: Per-client backoff multiplier for recontact delay escalation.
    # Formula: delay = cooldown_minutes × (backoff_multiplier ^ (attempt_number − 1))
    # Default 1.0 = flat delay (preserves existing behavior for all current clients).
    scheduler_backoff_multiplier: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0
    )

    # ---------------------------------------------------------------------------
    # Next Action Engine configuration (qora-next-action, Issue #47)
    # ---------------------------------------------------------------------------

    next_action_max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5
    )
    next_action_min_interest_for_followup: Mapped[int] = mapped_column(
        Integer, nullable=False, default=40
    )
    next_action_close_on_hard_rejection: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    # ---------------------------------------------------------------------------
    # Analysis locale configuration (qora-analysis-locale)
    # ---------------------------------------------------------------------------

    # Language for customer-facing Analysis text fields (summaries, descriptions,
    # evidence, reasons, notes). Internal enum/code fields stay canonical.
    # Default "Spanish" preserves backward-compat with all existing clients.
    analysis_language: Mapped[str] = mapped_column(
        String, nullable=False, default="Spanish"
    )

    # ---------------------------------------------------------------------------
    # Plan & entitlements (multi-tenant-readiness)
    # ---------------------------------------------------------------------------

    # Plan name from app/entitlements/catalog.py. "pilot" = all features, no limits.
    plan: Mapped[str] = mapped_column(
        String, nullable=False, default="pilot", server_default="pilot"
    )
    # Per-client exceptions to the plan, JSON stored as Text (nullable):
    # {"features": {"auto_dialer": true}, "limits": {"max_monthly_minutes": 500}}
    # Validated by app.entitlements.service.validate_overrides on write.
    entitlement_overrides: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None
    )

    # Issue #35 — Per-client extraction configuration (JSON stored as Text, nullable)
    # NULL = use base config + generic prompt (backward compat)
    extraction_config: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None
    )

    # ---------------------------------------------------------------------------
    # WorkOS AuthKit login (multi-tenant-auth)
    # ---------------------------------------------------------------------------

    # Links this client to exactly one WorkOS organization. Users whose
    # authenticate response returns this organization_id map to role=client
    # with client_ids=[this client's id], provided the client is_active.
    workos_organization_id: Mapped[str | None] = mapped_column(
        String, nullable=True, unique=True, default=None
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    # agent-config-inheritance (D11): single pointer to this client's active
    # ClientConfigRevision. NULL until the import migration (or an explicit
    # PATCH /clients/{client_id}/config) activates one.
    active_config_revision_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("client_config_revisions.id"),
        nullable=True,
        default=None,
    )

    # analysis-profiles (design.md P5-D2): single pointer to this client's
    # active ClientAnalysisProfileRevision. NULL until migration 0023 (or an
    # explicit apply-template/PUT) activates one.
    active_analysis_profile_revision_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("client_analysis_profile_revisions.id"),
        nullable=True,
        default=None,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Client id={self.id!r} name={self.name!r}>"

    # ---------------------------------------------------------------------------
    # DEPRECATED(Phase 7) — agent-specific columns moved to Agent model.
    # Kept nullable for rollback safety. Do NOT use in new code.
    # ---------------------------------------------------------------------------
    # NOTE: agent_name, voice_id, system_prompt_override, knowledge_base, model,
    # temperature, max_tokens, tools_enabled remain on Client for backward compat.
    # New code reads from Agent; these columns are only written during migration.
