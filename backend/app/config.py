"""Application configuration using pydantic-settings."""

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    # ------------------------------------------------------------------
    # OpenAI
    # ------------------------------------------------------------------
    openai_api_key: SecretStr
    openai_stt_model: str = "whisper-1"
    openai_llm_model: str = "gpt-4o"

    # ------------------------------------------------------------------
    # ElevenLabs
    # ------------------------------------------------------------------
    elevenlabs_api_key: SecretStr
    elevenlabs_model: str = "eleven_flash_v2_5"
    elevenlabs_voice_id: str = "pNInz6obpgDQGcFmaJgB"  # Adam
    elevenlabs_stability: float = 0.4  # 0.0 = expressive, 1.0 = stable
    elevenlabs_speed: float = 0.95  # 0.5 = slow, 1.5 = fast

    # ------------------------------------------------------------------
    # Twilio
    # ------------------------------------------------------------------
    twilio_account_sid: str
    twilio_auth_token: SecretStr
    twilio_phone_number: str

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    database_url: str = "sqlite+aiosqlite:///./callcenter.db"

    # ------------------------------------------------------------------
    # Server
    # ------------------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    # ------------------------------------------------------------------
    # Session
    # ------------------------------------------------------------------
    session_ttl_seconds: int = 300

    # ------------------------------------------------------------------
    # VAD
    # ------------------------------------------------------------------
    vad_silence_threshold_ms: int = 500
    vad_speech_threshold: float = 0.5

    # ------------------------------------------------------------------
    # STT
    # ------------------------------------------------------------------
    max_utterance_duration_s: int = 30

    # ------------------------------------------------------------------
    # LLM
    # ------------------------------------------------------------------
    max_history_messages: int = 10
    max_response_tokens: int = 300

    # ------------------------------------------------------------------
    # ElevenLabs Conversational AI (OPTIONAL)
    # Used for the managed Conversational AI path (VAD → STT → Custom LLM → TTS)
    # ------------------------------------------------------------------
    elevenlabs_conversational_agent_id: str = ""
    elevenlabs_conversational_api_key: SecretStr | None = None
    custom_llm_webhook_url: str = ""
    broker_name: str = "Quintana Seguros"

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

    @field_validator("session_ttl_seconds")
    @classmethod
    def validate_ttl(cls, v: int) -> int:
        if v < 60:
            raise ValueError("session_ttl_seconds must be at least 60")
        return v
