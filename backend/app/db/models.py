"""SQLAlchemy ORM models for V1-CallCenter.

Defines all database tables:
- Client: business customer that owns agents
- Agent: configured AI agent with personality, voice, and settings
- Conversation: single phone call session
- TranscriptSegment: individual turn in a conversation
- ConversationEvent: domain event emitted during conversation lifecycle
"""

from sqlalchemy import (
    Column,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


class Client(Base):
    """A business customer that owns one or more agents."""

    __tablename__ = "clients"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    phone_number = Column(String, nullable=False)
    twilio_account_sid = Column(String, nullable=False)
    twilio_auth_token = Column(String, nullable=False)
    twilio_phone_number = Column(String, nullable=False)
    created_at = Column(String, server_default=func.datetime("now"), nullable=False)
    updated_at = Column(
        String,
        server_default=func.datetime("now"),
        server_onupdate=func.datetime("now"),
        nullable=False,
    )
    is_active = Column(Integer, nullable=False, default=1)

    # Relationships
    agents = relationship("Agent", back_populates="client", lazy="select")
    conversations = relationship("Conversation", back_populates="client", lazy="select")

    def __repr__(self) -> str:
        return f"<Client(id={self.id}, name={self.name})>"


class Agent(Base):
    """A configured AI agent with personality, voice, and behavioral settings."""

    __tablename__ = "agents"

    id = Column(String, primary_key=True)
    client_id = Column(String, ForeignKey("clients.id"), nullable=False)
    name = Column(String, nullable=False)
    system_prompt = Column(Text, nullable=False)
    voice_id = Column(String, nullable=False)
    language = Column(String, nullable=False, default="es")
    max_history_messages = Column(Integer, nullable=False, default=10)
    max_response_tokens = Column(Integer, nullable=False, default=300)
    speech_end_silence_ms = Column(Integer, nullable=False, default=500)
    max_utterance_duration_s = Column(Integer, nullable=False, default=30)
    fallback_language = Column(String, nullable=False, default="es")
    created_at = Column(String, server_default=func.datetime("now"), nullable=False)
    updated_at = Column(
        String,
        server_default=func.datetime("now"),
        server_onupdate=func.datetime("now"),
        nullable=False,
    )
    is_active = Column(Integer, nullable=False, default=1)

    # Relationships
    client = relationship("Client", back_populates="agents", lazy="select")

    def __repr__(self) -> str:
        return f"<Agent(id={self.id}, name={self.name})>"


class Conversation(Base):
    """A single phone call session."""

    __tablename__ = "conversations"

    id = Column(String, primary_key=True)
    client_id = Column(String, ForeignKey("clients.id"), nullable=False)
    agent_id = Column(String, nullable=False)
    phone_number = Column(String, nullable=False)
    direction = Column(String, nullable=False, default="outbound")
    status = Column(String, nullable=False, default="active")
    started_at = Column(String, server_default=func.datetime("now"), nullable=False)
    ended_at = Column(String, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(String, server_default=func.datetime("now"), nullable=False)

    # Relationships
    client = relationship("Client", back_populates="conversations", lazy="select")
    transcript_segments = relationship(
        "TranscriptSegment",
        back_populates="conversation",
        lazy="select",
        cascade="all, delete-orphan",
    )
    events = relationship(
        "ConversationEvent",
        back_populates="conversation",
        lazy="select",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Conversation(id={self.id}, status={self.status})>"


class TranscriptSegment(Base):
    """A single turn in a conversation (one utterance + response)."""

    __tablename__ = "transcript_segments"

    id = Column(String, primary_key=True)
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=False)
    role = Column(String, nullable=False)  # 'user' or 'agent'
    text = Column(Text, nullable=False)
    timestamp = Column(String, server_default=func.datetime("now"), nullable=False)
    audio_duration_ms = Column(Integer, nullable=True)
    was_interrupted = Column(Integer, nullable=False, default=0)
    delivered_portion = Column(Text, nullable=True)
    meta_data = Column(
        "metadata", Text, nullable=True
    )  # JSON blob (mapped to 'metadata' column)

    # Relationships
    conversation = relationship(
        "Conversation", back_populates="transcript_segments", lazy="select"
    )

    def __repr__(self) -> str:
        return f"<TranscriptSegment(id={self.id}, role={self.role})>"


class ConversationEvent(Base):
    """A domain event emitted during the conversation lifecycle."""

    __tablename__ = "conversation_events"

    id = Column(String, primary_key=True)
    event_type = Column(String, nullable=False)
    session_id = Column(String, ForeignKey("conversations.id"), nullable=False)
    timestamp = Column(String, server_default=func.datetime("now"), nullable=False)
    payload = Column(Text, nullable=False)  # JSON blob
    version = Column(Integer, nullable=False, default=1)

    # Relationships
    conversation = relationship("Conversation", back_populates="events", lazy="select")

    def __repr__(self) -> str:
        return f"<ConversationEvent(id={self.id}, type={self.event_type})>"
