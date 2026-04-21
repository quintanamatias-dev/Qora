"""FastAPI dependency injection for V1-CallCenter.

Provides dependency functions that retrieve singleton components from
app.state, populated during the application lifespan startup.

Usage in route handlers:
    from fastapi import Depends
    from app.api.dependencies import get_settings, get_session_manager

    @router.get("/example")
    async def example(settings: Settings = Depends(get_settings)):
        ...
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

if TYPE_CHECKING:
    from app.config import Settings
    from app.agents.session_manager import SessionManager
    from app.recording.events import EventBus
    from app.recording.recorder import ConversationRecorder


async def get_settings(request: Request) -> Settings:
    """Yield the application Settings from app.state.

    Loaded once during lifespan startup.
    """
    return request.app.state.settings


async def get_session_manager(request: Request) -> SessionManager:
    """Yield the SessionManager from app.state.

    Initialized during lifespan startup with configured TTL.
    """
    return request.app.state.session_manager


async def get_event_bus(request: Request) -> EventBus:
    """Yield the EventBus from app.state.

    Initialized during lifespan startup with SQLite persistence.
    """
    return request.app.state.event_bus


async def get_recorder(request: Request) -> ConversationRecorder:
    """Yield the ConversationRecorder from app.state.

    Initialized during lifespan startup with the DB session factory.
    """
    return request.app.state.recorder
