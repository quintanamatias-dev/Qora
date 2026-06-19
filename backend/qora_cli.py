#!/usr/bin/env python3
"""QORA CLI — management commands for the call center platform.

Usage:
    python qora_cli.py create-client --id quintana-seguros --name "Quintana Seguros"
    python qora_cli.py list-clients
"""

from __future__ import annotations

import asyncio
import re
import shutil
import sys
from pathlib import Path

import click

# Slug validation: lowercase alphanumeric + hyphens, no leading/trailing hyphens
_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")

# Paths relative to this file (backend/)
_BACKEND_DIR = Path(__file__).resolve().parent
_CLIENTS_DIR = _BACKEND_DIR / "clients"
_TEMPLATE_DIR = _CLIENTS_DIR / "_template"


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------


@click.group()
def cli():
    """QORA management CLI."""


# ---------------------------------------------------------------------------
# create-client
# ---------------------------------------------------------------------------


@cli.command("create-client")
@click.option(
    "--id",
    "client_id",
    required=True,
    help="Client slug ID (e.g. quintana-seguros). Lowercase letters, digits, hyphens only.",
)
@click.option("--name", "company_name", required=True, help="Client/company display name.")
@click.option(
    "--agent-name", default="Jaumpablo", show_default=True, help="Agent name."
)
@click.option(
    "--voice-id",
    default="pNInz6obpgDQGcFmaJgB",
    show_default=True,
    help="ElevenLabs voice ID.",
)
def create_client(client_id: str, company_name: str, agent_name: str, voice_id: str):
    """Create a new client with directory structure and DB record.

    This command is idempotent:
    - If the DB record already exists, it skips insertion and logs a message.
    - If prompt.md already exists, it is NOT overwritten.
    - If knowledge.md already exists, it is NOT overwritten.
    """
    # 1. Validate slug
    if not _SLUG_RE.match(client_id):
        click.echo(
            f"[ERROR] Invalid slug: {client_id!r}. "
            "Must be lowercase letters, digits, and hyphens only — no leading or trailing hyphens.",
            err=True,
        )
        sys.exit(1)

    click.echo(f"[QORA] Creating client: {client_id}")

    # 2. Create backend/clients/{client_id}/ directory
    client_dir = _CLIENTS_DIR / client_id
    client_dir.mkdir(parents=True, exist_ok=True)
    click.echo(f"  ✓ Directory: {client_dir}")

    # 3. Copy prompt template (if not exists)
    prompt_path = client_dir / "prompt.md"
    template_path = _TEMPLATE_DIR / "prompt.md"
    if prompt_path.exists():
        click.echo("  ~ prompt.md already exists — skipping (not overwritten)")
    else:
        if template_path.exists():
            shutil.copy(template_path, prompt_path)
            click.echo("  ✓ Created prompt.md from template")
        else:
            # Write a minimal prompt inline if template is missing
            prompt_path.write_text(
                f"# {agent_name} — Agente de {company_name}\n\n"
                f"Sos {agent_name}, un asesor de {company_name}.\n\n"
                "Estás hablando con {{lead_name}}.\n\n"
                "[Personalizar este template]\n",
                encoding="utf-8",
            )
            click.echo(
                "  ✓ Created prompt.md (inline template — no _template/prompt.md found)"
            )

    # 4. Create empty knowledge.md (if not exists)
    knowledge_path = client_dir / "knowledge.md"
    if knowledge_path.exists():
        click.echo("  ~ knowledge.md already exists — skipping")
    else:
        knowledge_path.write_text(
            f"# Información de {company_name}\n\n"
            "[Agregar aquí información relevante sobre la empresa, productos, precios, FAQs, etc.]\n",
            encoding="utf-8",
        )
        click.echo("  ✓ Created knowledge.md (placeholder)")

    # 5. Insert DB record (idempotent — skip if exists)
    asyncio.run(_upsert_client_db(client_id, company_name, agent_name, voice_id))

    click.echo(f"\n[QORA] ✓ Client {client_id!r} ready.")


async def _upsert_client_db(
    client_id: str,
    company_name: str,
    agent_name: str,
    voice_id: str,
) -> None:
    """Insert Client record if it doesn't exist. Idempotent."""
    # Import here to avoid circular imports and async-at-import issues
    import sys
    import os

    # Ensure backend/ is importable
    sys.path.insert(0, str(_BACKEND_DIR))
    os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_BACKEND_DIR}/qora.db")

    from app.core.config import Settings
    from app.core import database as db_module
    from app.tenants.service import get_client, create_client as svc_create_client
    from scripts.migrate import run_migrations

    # Ensure schema exists before opening a session.
    # init_db() no longer calls create_all() (PR2 cutover); migrations must run first.
    run_migrations()

    settings = Settings()
    await db_module.init_db(settings)

    try:
        async with db_module.async_session_factory() as session:
            existing = await get_client(session, client_id)
            if existing is not None:
                click.echo(
                    f"  ~ DB record for {client_id!r} already exists — skipping insertion"
                )
                return

            await svc_create_client(
                session,
                id=client_id,
                name=company_name,
                agent_name=agent_name,
                voice_id=voice_id,
                is_active=True,
            )
            await session.commit()
            click.echo(f"  ✓ DB record created for {client_id!r}")
    finally:
        await db_module.close_db()


# ---------------------------------------------------------------------------
# list-clients
# ---------------------------------------------------------------------------


@cli.command("list-clients")
def list_clients():
    """List all clients in the DB."""
    asyncio.run(_list_clients_db())


async def _list_clients_db() -> None:
    import sys
    import os

    sys.path.insert(0, str(_BACKEND_DIR))
    os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_BACKEND_DIR}/qora.db")

    from app.core.config import Settings
    from app.core import database as db_module
    from sqlalchemy import select
    from app.tenants.models import Client
    from scripts.migrate import run_migrations

    # Ensure schema exists before opening a session.
    # init_db() no longer calls create_all() (PR2 cutover); migrations must run first.
    run_migrations()

    settings = Settings()
    await db_module.init_db(settings)

    try:
        async with db_module.async_session_factory() as session:
            result = await session.execute(select(Client))
            clients = result.scalars().all()

            if not clients:
                click.echo("No clients found.")
                return

            click.echo(f"{'ID':<30} {'NAME':<30} {'AGENT':<20} {'ACTIVE'}")
            click.echo("-" * 85)
            for c in clients:
                click.echo(
                    f"{c.id:<30} {c.name:<30} {c.agent_name:<20} {c.is_active}"
                )
    finally:
        await db_module.close_db()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cli()
