"""Task 1.1 — the MCP module is importable and exposes a startable server
without starting a long-running stdio process."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_mcp_module_is_importable_and_starts():
    from app.mcp.server import mcp_server

    tools = await mcp_server.list_tools()
    assert len(tools) > 0
