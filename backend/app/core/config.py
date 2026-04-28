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
    elevenlabs_agent_id: str = ""
    elevenlabs_voice_id: str = "pNInz6obpgDQGcFmaJgB"  # Adam
    elevenlabs_model: str = "eleven_flash_v2_5"
    elevenlabs_stability: float = 0.4
    elevenlabs_speed: float = 0.95

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

    # ------------------------------------------------------------------
    # Filler
    # ------------------------------------------------------------------
    filler_timeout_ms: int = 500  # fallback filler if LLM too slow

    # ------------------------------------------------------------------
    # QORA defaults
    # ------------------------------------------------------------------
    default_broker_name: str = "Quintana Seguros"
    default_agent_name: str = "Jaumpablo"

    # ------------------------------------------------------------------
    # n8n Orchestration (feature-flagged, all off by default)
    # ------------------------------------------------------------------
    # Feature flag — when False, zero behavior change to existing code.
    n8n_enabled: bool = False
    # Outbound webhook URL (n8n webhook trigger endpoint)
    n8n_webhook_url: str = ""
    # Outbound HMAC signing secret — for X-Webhook-Signature on triggered requests
    n8n_webhook_secret: SecretStr = SecretStr("")
    # Inbound static API key — for X-Internal-Api-Key on internal API endpoints
    n8n_internal_api_key: SecretStr = SecretStr("")
    # Outbound HTTP timeout for webhook POST (seconds)
    n8n_timeout_seconds: int = 5

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
