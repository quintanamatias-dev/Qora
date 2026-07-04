"""QORA application configuration using pydantic-settings."""

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings

# ---------------------------------------------------------------------------
# Known weak placeholder values — CRITICAL and HIGH secrets must not use these.
# Case-insensitive comparison is applied; see validate_required_secrets().
# Source of truth: openspec/changes/phase-b-secrets-management/specs/secrets-validation/spec.md
# ---------------------------------------------------------------------------
_WEAK_PLACEHOLDERS: frozenset[str] = frozenset({
    "change-me-before-production",
    "your-key-here",
    "todo",
    "replace_me",
    "xxx",
    "test",
    "changeme",
})


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _validate_secret_field(
    field_name: str,
    secret: SecretStr | None,
    tier: str,
    errors: list[str],
) -> None:
    """Validate a single secret field against the presence and placeholder rules.

    Appends a human-readable error message to ``errors`` when validation fails.
    The secret VALUE is never included in any error message.

    Args:
        field_name: The environment variable name (e.g. "OPENAI_API_KEY").
        secret: The SecretStr value loaded from the environment, or None.
        tier: "CRITICAL" or "HIGH" — used in the error message for context.
        errors: List to accumulate error strings (mutated in place).
    """
    if secret is None:
        errors.append(
            f"{field_name} is required ({tier}) but is not set. "
            f"Add {field_name} to your .env file."
        )
        return

    value = secret.get_secret_value()
    if not value.strip():
        errors.append(
            f"{field_name} is required ({tier}) but is empty. "
            f"Set {field_name} to a non-empty value."
        )
        return

    if value.strip().lower() in _WEAK_PLACEHOLDERS:
        errors.append(
            f"{field_name} ({tier}) contains a known weak placeholder. "
            f"Replace it with a real credential before starting the application. "
            f"Do not use placeholder values for {tier} secrets."
        )


class Settings(BaseSettings):
    """QORA application settings loaded from environment variables and .env file."""

    # ------------------------------------------------------------------
    # OpenAI
    # ------------------------------------------------------------------
    openai_api_key: SecretStr
    openai_model: str = "gpt-4o"
    openai_model_fast: str = "gpt-4o-mini"

    # ------------------------------------------------------------------
    # ElevenLabs
    # ------------------------------------------------------------------
    elevenlabs_api_key: SecretStr
    elevenlabs_agent_id: str = "agent_8201kra4wjhve0srcwgbtwfetr5n"  # Qora Demo agent
    elevenlabs_voice_id: str = "4wDRKlxcHNOFO5kBvE81"  # Melisa (Sofia — Qora demo)
    elevenlabs_model: str = "eleven_flash_v2_5"
    elevenlabs_stability: float = 0.4
    elevenlabs_speed: float = 0.95
    elevenlabs_similarity_boost: float = 0.75

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    database_url: str = "sqlite+aiosqlite:///./qora.db"

    # ------------------------------------------------------------------
    # App
    # ------------------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    debug: bool = False
    frontend_url: str = "http://localhost:5173"

    # ------------------------------------------------------------------
    # Filler
    # ------------------------------------------------------------------
    filler_timeout_ms: int = 500  # fallback filler if LLM too slow

    # ------------------------------------------------------------------
    # QORA defaults
    # ------------------------------------------------------------------
    default_company_name: str = "Quintana Seguros"
    default_agent_name: str = "Jaumpablo"

    # ------------------------------------------------------------------
    # Authentication (Phase B5 — PR #1: Foundation + Admin Auth)
    # ------------------------------------------------------------------
    # Admin API protection. Set to a strong random secret in production.
    # Phase C: replaced by require_jwt — zero router changes needed.
    qora_api_key: SecretStr | None = None

    # Toggle OpenAPI docs (/docs + /redoc). Default True for dev; set False in prod.
    qora_docs_enabled: bool = True

    # Demo identity — used by PR #2 (Session Auth + Demo).
    # Declared here so Settings is the single source of truth.
    qora_demo_client_id: str | None = None
    qora_demo_agent_id: str | None = None

    # Session TTL — used by PR #2 AuthorizedSession lifecycle cleanup.
    qora_session_ttl_seconds: int = 14400  # 4 hours default

    # Webhook auth — declared here for PR #3 (Webhook Auth + CORS).
    # NOT enforced in PR #1 or PR #2. Defaults keep the current open behaviour.
    # Wiring (require_webhook_secret) is implemented in PR #3.
    qora_webhook_secret: SecretStr | None = None
    qora_webhook_auth_enabled: bool = False  # default: off — no webhook auth yet

    # CORS origins — declared here for PR #3 (Webhook Auth + CORS).
    # NOTE (WU2 re-review RE3): outbound_without_webhook_auth_warning is a derived
    # property (see below). When enable_outbound_calls=True AND
    # qora_webhook_auth_enabled=False, the application lifespan logs a structured
    # WARNING at startup. Production/live-call configs MUST set:
    #   QORA_WEBHOOK_AUTH_ENABLED=true
    #   QORA_WEBHOOK_SECRET=<strong-random-secret>
    # before enabling ENABLE_OUTBOUND_CALLS=true.
    # NOT enforced in PR #1 or PR #2. The CORSMiddleware in main.py still uses
    # allow_origins=["*"] until PR #3 wires this setting.
    # comma-separated list; "*" = open (dev default — matches current behaviour)
    qora_allowed_origins: str = "*"

    # ------------------------------------------------------------------
    # Background Job Executor (Phase B10)
    # ------------------------------------------------------------------
    # Feature flag: controls whether post-call jobs use the durable executor
    # (DB-backed retry/recovery) or the legacy fire-and-forget create_task path.
    # Default: False — deploy migration + code with flag off (no behavior change).
    # Set ENABLE_JOB_EXECUTOR=true to enable durable job execution.
    # Rollback: set flag back to False; Alembic downgrade drops background_jobs table.
    # Design: openspec/changes/phase-b-background-job-durability/design.md
    enable_job_executor: bool = False

    # ------------------------------------------------------------------
    # Outbound Call Trigger (Phase C2)
    # ------------------------------------------------------------------
    # Feature flag: gates ALL real telephony actions. Default False — no calls
    # are placed and no charges incurred until explicitly enabled by the operator.
    # Matches enable_job_executor pattern: single operator toggle.
    # Rollback: set to False (or remove) — immediate; no code change needed.
    # Migration rollback: alembic downgrade -1 removes new telephony columns.
    # Design: openspec/changes/phase-c2-outbound-call-trigger/design.md
    enable_outbound_calls: bool = False

    # ------------------------------------------------------------------
    # Call SIP Observability (C3 — call-observability-reconciliation)
    # ------------------------------------------------------------------
    # Maximum number of unreconciled sessions to process per reconciliation sweep cycle.
    # Prevents hitting ElevenLabs API rate limits on large backlogs.
    # Conservative default (10): clears typical backlogs in 2-3 sweep cycles (5-min interval).
    # Design: openspec/changes/call-observability-reconciliation/design.md — Per-sweep cap.
    reconciliation_sweep_cap: int = 10

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid:
            raise ValueError(f"log_level must be one of {valid}, got '{v}'")
        return upper

    @model_validator(mode="after")
    def validate_required_secrets(self) -> "Settings":
        """Hard-fail startup when CRITICAL or HIGH secrets are absent, empty, or weak placeholders.

        Spec (secrets-validation — Requirement: Critical Secret Fail-Fast):
            OPENAI_API_KEY and ELEVENLABS_API_KEY must be present and non-empty. If absent
            or empty, startup aborts and the error message names the missing variable.

        Spec (secrets-validation — Requirement: Platform API Key Required):
            QORA_API_KEY is required in ALL environments including local dev.

        Spec (secrets-validation — Requirement: Placeholder Value Rejection):
            Known weak placeholder values are rejected for HIGH and CRITICAL secrets.
            The error message identifies the variable and the placeholder pattern.

        Secret values are NEVER logged or included in error messages.
        """
        errors: list[str] = []

        # CRITICAL: OPENAI_API_KEY
        _validate_secret_field(
            field_name="OPENAI_API_KEY",
            secret=self.openai_api_key,
            tier="CRITICAL",
            errors=errors,
        )

        # CRITICAL: ELEVENLABS_API_KEY
        _validate_secret_field(
            field_name="ELEVENLABS_API_KEY",
            secret=self.elevenlabs_api_key,
            tier="CRITICAL",
            errors=errors,
        )

        # HIGH: QORA_API_KEY (required in all environments)
        _validate_secret_field(
            field_name="QORA_API_KEY",
            secret=self.qora_api_key,
            tier="HIGH",
            errors=errors,
        )

        if errors:
            raise ValueError(
                "Startup aborted — required secret(s) are missing or invalid:\n"
                + "\n".join(f"  • {e}" for e in errors)
            )

        return self

    @property
    def outbound_without_webhook_auth_warning(self) -> bool:
        """True when outbound calls are enabled but webhook auth is disabled.

        This combination means real outbound calls can be placed, but the
        elevenlabs-postcall and /end webhook endpoints are unauthenticated.
        An adversary who knows the webhook URL can mark outbound sessions as
        completed without placing a real call, corrupting billing records.

        Production / live-call configurations MUST set:
            QORA_WEBHOOK_AUTH_ENABLED=true
            QORA_WEBHOOK_SECRET=<strong-random-secret>
        before enabling ENABLE_OUTBOUND_CALLS=true.

        This property is used by the lifespan startup logger to emit a
        structured WARNING when the risky config is detected.
        (WU2 re-review RE3)
        """
        return self.enable_outbound_calls and not self.qora_webhook_auth_enabled

    @model_validator(mode="after")
    def validate_webhook_secret_when_enabled(self) -> "Settings":
        """Enforce startup-fail when webhook auth is enabled but secret is absent or empty.

        Spec (webhook-auth/spec.md — Requirement: Config-Driven Secret):
            "If QORA_WEBHOOK_AUTH_ENABLED=true and QORA_WEBHOOK_SECRET is not set,
             startup MUST fail with a configuration error before serving any requests."

        An empty QORA_WEBHOOK_SECRET provides no security value and is treated as
        absent — the validator rejects it with the same error.

        This fires during Settings.__init__ (pydantic model construction), which
        happens before the FastAPI lifespan starts, before any router is registered,
        and before any request can be served.
        """
        if self.qora_webhook_auth_enabled:
            secret = self.qora_webhook_secret
            # Reject: absent (None) or empty string after unwrapping SecretStr.
            secret_value = secret.get_secret_value() if secret is not None else None
            if not secret_value:
                raise ValueError(
                    "QORA_WEBHOOK_AUTH_ENABLED=true but QORA_WEBHOOK_SECRET is not set or is empty. "
                    "Set QORA_WEBHOOK_SECRET to a strong random value before enabling webhook auth. "
                    "Startup is aborted to prevent an insecure configuration from serving requests."
                )
        return self
