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
