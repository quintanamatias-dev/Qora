"""QORA Tenants — Admin/debug router for tenant config inspection."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.tenants.service import get_client

router = APIRouter(prefix="/tenants", tags=["tenants"])


async def get_db_session():
    """FastAPI dependency that yields an async DB session."""
    from app.core.database import async_session_factory

    if async_session_factory is None:
        raise RuntimeError("Database not initialized.")

    async with async_session_factory() as session:
        yield session


@router.get("/{client_id}")
async def get_tenant(
    client_id: str,
    session: AsyncSession = Depends(get_db_session),
):
    """Return tenant configuration for a given client_id.

    Returns:
        JSON with client config fields.

    Raises:
        404: If the client_id does not exist.
    """
    client = await get_client(session, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail={"error": "client not found"})

    return {
        "id": client.id,
        "name": client.name,
        "agent_name": client.agent_name,
        "voice_id": client.voice_id,
        "model": client.model,
        "temperature": client.temperature,
        "max_tokens": client.max_tokens,
        "tools_enabled": client.tools_enabled,
        "is_active": client.is_active,
        "created_at": client.created_at.isoformat() if client.created_at else None,
    }
