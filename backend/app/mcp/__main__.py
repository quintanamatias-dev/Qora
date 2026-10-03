"""`uv run python -m app.mcp` — starts the QORA data MCP server over stdio.

Opens its own async DB session factory from Settings().database_url via the
existing app.core.database factory, then serves tool calls until the stdio
transport closes.
"""

from __future__ import annotations

import asyncio

from app.core.config import Settings
from app.core.database import create_engine_and_session
from app.mcp.server import mcp_server


async def _main() -> None:
    settings = Settings()
    create_engine_and_session(settings.database_url)
    await mcp_server.run_stdio_async()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
