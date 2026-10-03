"""QORA data MCP server (design.md M-D1) — read-only tools over stdio.

Every registered tool opens its own async DB session via
app.core.database.get_session() and delegates to the service layer/ORM — no
tool performs an insert, update, or delete. REGISTERED_TOOLS mirrors the
server's tool registry so the never-secrets guard and the tool-count
regression test can inspect every tool's output shape without needing a
live stdio transport.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from mcp.server.mcpserver import MCPServer

from app.core.database import get_session
from app.mcp import schemas
from app.mcp.tools import agents as agents_tools
from app.mcp.tools import calls as calls_tools
from app.mcp.tools import clients as clients_tools
from app.mcp.tools import leads as leads_tools


@dataclass(frozen=True)
class ToolSpec:
    name: str
    output_model: Any
    func: Callable[..., Any]


mcp_server = MCPServer(name="qora-data", version="0.1.0")


async def _list_clients(limit: int = 50, offset: int = 0) -> list[schemas.ClientSummary]:
    async with get_session() as session:
        return await clients_tools.list_clients(session, limit=limit, offset=offset)


async def _get_client(client_id: str) -> schemas.ClientSummary | None:
    async with get_session() as session:
        return await clients_tools.get_client(session, client_id)


async def _list_agents(
    client_id: str, limit: int = 50, offset: int = 0
) -> list[schemas.AgentSummary]:
    async with get_session() as session:
        return await agents_tools.list_agents(
            session, client_id, limit=limit, offset=offset
        )


async def _get_agent(client_id: str, agent_id: str) -> schemas.AgentEffectiveConfig | None:
    async with get_session() as session:
        return await agents_tools.get_agent(session, client_id, agent_id)


async def _list_leads(
    client_id: str,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[schemas.LeadSummary]:
    async with get_session() as session:
        return await leads_tools.list_leads(
            session, client_id, status=status, limit=limit, offset=offset
        )


async def _get_lead(client_id: str, lead_id: str) -> schemas.LeadDetail | None:
    async with get_session() as session:
        return await leads_tools.get_lead(session, client_id, lead_id)


async def _list_calls(
    client_id: str, limit: int = 50, offset: int = 0
) -> list[schemas.CallSummary]:
    async with get_session() as session:
        return await calls_tools.list_calls(session, client_id, limit=limit, offset=offset)


async def _get_call(client_id: str, call_id: str) -> schemas.CallDetail | None:
    async with get_session() as session:
        return await calls_tools.get_call(session, client_id, call_id)


REGISTERED_TOOLS: list[ToolSpec] = [
    ToolSpec("list_clients", schemas.ClientSummary, _list_clients),
    ToolSpec("get_client", schemas.ClientSummary, _get_client),
    ToolSpec("list_agents", schemas.AgentSummary, _list_agents),
    ToolSpec("get_agent", schemas.AgentEffectiveConfig, _get_agent),
    ToolSpec("list_leads", schemas.LeadSummary, _list_leads),
    ToolSpec("get_lead", schemas.LeadDetail, _get_lead),
    ToolSpec("list_calls", schemas.CallSummary, _list_calls),
    ToolSpec("get_call", schemas.CallDetail, _get_call),
]

for _spec in REGISTERED_TOOLS:
    mcp_server.add_tool(_spec.func, name=_spec.name)
