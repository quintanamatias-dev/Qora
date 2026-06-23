"""QORA application configuration using pydantic-settings."""

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings


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
    # NOT enforced in PR #1 or PR #2. The CORSMiddleware in main.py still uses
    # allow_origins=["*"] until PR #3 wires this setting.
    # comma-separated list; "*" = open (dev default — matches current behaviour)
    qora_allowed_origins: str = "*"

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
