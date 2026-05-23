"""QORA PromptLoader — Filesystem-based per-client prompt system.

Loads prompt templates from ``backend/clients/{client_id}/prompt.md`` with a
fallback to the hardcoded ``JAUMPABLO_PROMPT_TEMPLATE`` when the file is absent.
Optionally appends a knowledge base from ``knowledge.md`` under a standard
section heading.

Architecture decision (design.md AD-1):
    Template syntax is ``{{variable}}`` rendered via ``re.sub``.  No Jinja2
    dependency; no risk of ``str.format`` breaking on curly braces in prompt
    text.

Architecture decision (design.md AD-3):
    ``PromptLoader`` accepts an optional ``clients_dir`` to make it easily
    testable with ``tmp_path`` without monkeypatching class attributes.

Architecture decision (design.md AD-4):
    Token estimation uses ``len(text.split()) * 1.3`` — accurate enough for
    Spanish text, zero additional dependencies.

Architecture decision (design.md AD-6):
    Variable values are sanitised by replacing ``{{`` with ``{ {`` before
    substitution, preventing template injection via lead data.

CAP-2 (qora-memory-in-prompt):
    ``_build_variables`` is now async and accepts an optional ``db`` parameter.
    When ``db`` and ``lead`` are provided, calls ``build_memory_context`` to
    inject real call_history, is_returning_caller, call_number. confirmed_facts
    remains as an empty legacy placeholder.
    Falls back to empty defaults on any exception (structured error log emitted).

Covers: T1.2, T2.2, T2.3, T22, T23.
"""

from __future__ import annotations

import asyncio
import logging
import re
import structlog
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.tenants.models import Agent, Client
    from app.leads.models import Lead

logger = logging.getLogger(__name__)
_structlog = structlog.get_logger()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_KNOWLEDGE_TOKENS = 2000

# Default clients directory — resolved relative to this file so it works
# regardless of the working directory.  Tests override this via PromptLoader(clients_dir=…).
_DEFAULT_CLIENTS_DIR = Path(__file__).resolve().parents[2] / "clients"


# ---------------------------------------------------------------------------
# Agent → Client adapter for backward-compatible rendering
# ---------------------------------------------------------------------------


class _AgentClientAdapter:
    """Thin adapter that makes an Agent look like a Client for prompt rendering.

    The original render() and render_system_prompt() functions accept a Client
    object and read: id, broker_name, agent_name.  This adapter exposes those
    attributes using Agent data so existing rendering logic works unchanged.
    """

    def __init__(self, agent: "Agent", client: "Client | None" = None) -> None:
        self._agent = agent
        self._client = client

    @property
    def id(self) -> str:
        return getattr(self._agent, "client_id", None) or "unknown"

    @property
    def broker_name(self) -> str:
        if self._client is not None:
            return getattr(self._client, "broker_name", "")
        return ""

    @property
    def agent_name(self) -> str:
        return getattr(self._agent, "name", "Jaumpablo")


# ---------------------------------------------------------------------------
# PromptLoader
# ---------------------------------------------------------------------------


class PromptLoader:
    """Load, render, and inject per-client system prompts.

    Args:
        clients_dir: Root of the ``clients/`` tree.  Defaults to
            ``<repo-root>/clients``.  Override in tests with ``tmp_path``.
    """

    def __init__(self, clients_dir: Path | None = None) -> None:
        self.clients_dir = (
            clients_dir if clients_dir is not None else _DEFAULT_CLIENTS_DIR
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def load_prompt(self, client_id: str) -> str:
        """Return the prompt template for *client_id*.

        Loads ``clients/{client_id}/prompt.md``.  Falls back to
        ``JAUMPABLO_PROMPT_TEMPLATE`` when the file is absent.

        Args:
            client_id: The slug identifying the client (e.g. ``"quintana-seguros"``).

        Returns:
            Template string with ``{{variable}}`` placeholders — NOT yet rendered.
        """
        from app.prompts.insurance_agent import JAUMPABLO_PROMPT_TEMPLATE

        prompt_path = self.clients_dir / client_id / "prompt.md"
        if await asyncio.to_thread(prompt_path.exists):
            return await asyncio.to_thread(prompt_path.read_text, encoding="utf-8")
        return JAUMPABLO_PROMPT_TEMPLATE

    async def load_agent_skills(self, client_id: str, agent_slug: str) -> str:
        """Return the registry-based ## Available Skills index block for the agent.

        Reads ``clients/{client_id}/agents/{agent_slug}/skills/registry.yaml`` and
        builds a compact index text for injection into the system prompt.

        The old glob-all behavior (concatenating all *.agent-skill.md files) is
        REMOVED. No registry.yaml → empty string. Empty registry → empty string.
        There is NO fallback to globbing skill files.

        Args:
            client_id: Client slug (e.g. ``"quintana-seguros"``).
            agent_slug: Agent slug (e.g. ``"aria"``).

        Returns:
            Formatted ``## Available Skills`` index block, or ``""`` if no registry.
        """
        from app.prompts.skill_loader import load_skill_registry, build_skills_index

        entries = await load_skill_registry(
            client_id=client_id,
            agent_slug=agent_slug,
            clients_dir=self.clients_dir,
        )
        return build_skills_index(entries)

    async def load_skill_registry_entries(
        self, client_id: str, agent_slug: str
    ) -> list:
        """Return the raw list of SkillRegistryEntry objects for the agent.

        Unlike load_agent_skills() which returns formatted index text, this
        method returns the parsed entry objects used by the load_skill handler
        for allowlist validation.

        Args:
            client_id: Client slug (e.g. ``"quintana-seguros"``).
            agent_slug: Agent slug (e.g. ``"aria"``).

        Returns:
            List of SkillRegistryEntry objects, empty if no registry.
        """
        from app.prompts.skill_loader import load_skill_registry

        return await load_skill_registry(
            client_id=client_id,
            agent_slug=agent_slug,
            clients_dir=self.clients_dir,
        )

    async def load_agent_system_prompt(
        self, client_id: str, agent_slug: str
    ) -> str | None:
        """Return the canonical filesystem prompt for one agent, if present.

        Runtime agent prompts live at
        ``clients/{client_id}/agents/{agent_slug}/system-prompt.md``.
        This file is the source of truth when it exists; DB prompts are only a
        legacy fallback for agents not yet migrated to the filesystem layout.
        """
        prompt_path = (
            self.clients_dir / client_id / "agents" / agent_slug / "system-prompt.md"
        )
        if await asyncio.to_thread(prompt_path.exists):
            return await asyncio.to_thread(prompt_path.read_text, encoding="utf-8")
        return None

    async def load_knowledge(self, client_id: str) -> str | None:
        """Return the knowledge base for *client_id*, or ``None``.

        Loads ``clients/{client_id}/knowledge.md``.  Returns ``None`` when the
        file (or directory) does not exist.

        Args:
            client_id: Client slug.

        Returns:
            Raw knowledge base content, or ``None`` if unavailable.
        """
        knowledge_path = self.clients_dir / client_id / "knowledge.md"
        if await asyncio.to_thread(knowledge_path.exists):
            return await asyncio.to_thread(knowledge_path.read_text, encoding="utf-8")
        return None

    async def render_for_agent(
        self,
        agent: "Agent",
        lead: "Lead | None" = None,
        call_count: int = 1,
        db: "AsyncSession | None" = None,
        client: "Client | None" = None,
    ) -> str:
        """Render the system prompt using Agent as the primary config source.

        Priority order:
        1. filesystem clients/{client_id}/agents/{agent_slug}/system-prompt.md
        2. agent.system_prompt (legacy DB fallback)
        3. filesystem clients/{client_id}/prompt.md or JAUMPABLO_PROMPT_TEMPLATE
           (legacy client fallback, uses agent.name for {{agent_name}})

        Knowledge base:
        - Agent.knowledge_base is legacy and is not appended automatically.
        - Filesystem knowledge.md is also not used on the Agent path; runtime
          knowledge belongs in registry skills loaded on demand.

        Args:
            agent: Agent ORM (or mock) with system_prompt, knowledge_base, name, client_id.
            lead: Optional lead ORM instance.
            call_count: How many times the lead has been called.
            db: Optional async DB session for memory context.
            client: Optional Client ORM — used for broker_name in template rendering.
                    If None, broker_name defaults to empty string.

        Returns:
            Fully rendered system prompt string.
        """
        from app.prompts.insurance_agent import (
            JAUMPABLO_PROMPT_TEMPLATE,
            render_system_prompt,
        )

        agent_system_prompt = getattr(agent, "system_prompt", None)
        client_id = getattr(agent, "client_id", None) or "unknown"
        agent_slug = getattr(agent, "slug", None)
        if not isinstance(agent_slug, str) or not agent_slug.strip():
            agent_slug = str(getattr(agent, "name", "agent")).lower().replace(" ", "-")
        file_system_prompt = await self.load_agent_system_prompt(client_id, agent_slug)

        # ------------------------------------------------------------------
        # Build prompt body
        # ------------------------------------------------------------------
        if file_system_prompt:
            # Filesystem prompt is the source of truth — render as a {{variable}}
            # template so call_history, confirmed_facts, lead_name, etc. are
            # substituted.
            prompt_body = await self._render_template(
                file_system_prompt,
                _AgentClientAdapter(agent, client),
                lead,
                call_count,
                db=db,
            )
        elif agent_system_prompt:
            # Legacy DB fallback for agents not yet migrated to filesystem.
            prompt_body = await self._render_template(
                agent_system_prompt,
                _AgentClientAdapter(agent, client),
                lead,
                call_count,
                db=db,
            )
        else:
            # Fallback: load from filesystem or JAUMPABLO template
            template = await self.load_prompt(client_id)

            if template is JAUMPABLO_PROMPT_TEMPLATE:
                # Use the original renderer — it handles {single-brace} format
                # Build a minimal client-like object with agent's name
                _agent_as_client = _AgentClientAdapter(agent, client)
                fallback_memory = None
                if db is not None and lead is not None:
                    try:
                        from app.memory import build_memory_context

                        fallback_memory = await build_memory_context(db, lead)
                    except Exception as exc:
                        _structlog.error(
                            "memory_context_failed",
                            lead_id=getattr(lead, "id", None),
                            error_type=type(exc).__name__,
                            error_msg=str(exc),
                            branch="render_for_agent_fallback",
                        )
                prompt_body = render_system_prompt(
                    _agent_as_client, lead, call_count, memory=fallback_memory
                )
            else:
                prompt_body = await self._render_template(
                    template,
                    _AgentClientAdapter(agent, client),
                    lead,
                    call_count,
                    db=db,
                )

        # NOTE: We intentionally do NOT append Agent.knowledge_base here.
        # It is a legacy field; runtime knowledge belongs in registry skills
        # loaded through load_skill, not in every system prompt.

        return prompt_body

    async def render(
        self,
        client: "Client",
        lead: "Lead | None" = None,
        call_count: int = 1,
        db: "AsyncSession | None" = None,
    ) -> str:
        """Render the system prompt for *client* with optional *lead* context.

        Steps:
        1. Load prompt template (file or fallback).
        2. If template is the fallback hardcoded one, delegate to
           ``render_system_prompt`` from ``insurance_agent`` — it already
           handles variable substitution for the original ``{variable}``
           format.
        3. If template is from a file, build the variables dict (async),
           sanitise all values, then substitute ``{{variable}}`` placeholders
           via regex.
        4. Load ``knowledge.md``, truncate to ``MAX_KNOWLEDGE_TOKENS``, and
           append under ``## INFORMACIÓN DE LA EMPRESA``.

        Args:
            client: Client (tenant) ORM instance with ``id``, ``broker_name``,
                and ``agent_name``.
            lead: Optional lead ORM instance.  ``None`` uses safe defaults.
            call_count: Number of times the lead has been called (>1 = returning
                caller context).
            db: Optional async DB session.  When provided together with *lead*,
                ``build_memory_context`` is called to inject real memory
                variables (call_history, confirmed_facts, etc.).

        Returns:
            Fully rendered system prompt string.  No ``{{}}`` placeholders remain.
        """
        from app.prompts.insurance_agent import (
            JAUMPABLO_PROMPT_TEMPLATE,
            render_system_prompt,
        )

        client_id = client.id if client else "unknown"
        template = await self.load_prompt(client_id)

        # ------------------------------------------------------------------
        # Render the prompt body
        # ------------------------------------------------------------------
        if template is JAUMPABLO_PROMPT_TEMPLATE:
            # Delegate to original renderer — handles the {single-brace} format.
            # REQ-2.8: Build memory context and pass it so render_system_prompt
            # uses real call_number / is_returning_caller data.
            fallback_memory = None
            if db is not None and lead is not None:
                try:
                    from app.memory import build_memory_context

                    fallback_memory = await build_memory_context(db, lead)
                except Exception as exc:
                    _structlog.error(
                        "memory_context_failed",
                        lead_id=getattr(lead, "id", None),
                        error_type=type(exc).__name__,
                        error_msg=str(exc),
                        branch="fallback_jaumpablo",
                    )
                    # fallback_memory stays None — render_system_prompt uses call_count
            prompt_body = render_system_prompt(
                client, lead, call_count, memory=fallback_memory
            )
        else:
            prompt_body = await self._render_template(
                template, client, lead, call_count, db=db
            )

        # ------------------------------------------------------------------
        # Knowledge injection
        # ------------------------------------------------------------------
        knowledge = await self.load_knowledge(client_id)
        if knowledge:
            knowledge = self._truncate_knowledge(knowledge, client_id=client_id)
            prompt_body = f"{prompt_body}\n\n## INFORMACIÓN DE LA EMPRESA\n{knowledge}"

        return prompt_body

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _build_variables(
        self,
        client: "Client",
        lead: "Lead | None",
        call_count: int,
        db: "AsyncSession | None" = None,
    ) -> dict[str, str]:
        """Build the substitution dict from client + lead data.

        CAP-2: Now async. Accepts optional ``db`` parameter.
        When ``db`` and ``lead`` are provided, calls ``build_memory_context``
        to inject real memory variables. Falls back to empty defaults on
        any exception, logging ``memory_context_failed``.

        Includes memory variables (call_history, confirmed_facts,
        is_returning_caller, call_number). call_history/is_returning_caller/
        call_number use real values when db+lead are provided; confirmed_facts
        is intentionally always empty.
        """
        from app.prompts.insurance_agent import RETURNING_CALLER_CONTEXT

        broker_name = client.broker_name if client else "la aseguradora"
        agent_name = client.agent_name if client else "Jaumpablo"

        if lead is not None:
            lead_name = lead.name or "el cliente"
            car_make = lead.car_make or "tu auto"
            car_model = lead.car_model or ""
            car_year = str(lead.car_year) if lead.car_year else ""
            current_insurance = lead.current_insurance or "no tiene"
        else:
            lead_name = "el cliente"
            car_make = "tu auto"
            car_model = ""
            car_year = ""
            current_insurance = "no tiene"

        returning_caller_context = ""
        if call_count > 1:
            returning_caller_context = RETURNING_CALLER_CONTEXT.format(
                call_count=call_count
            )

        # CAP-6 memory variables — default values per REQ-2.4
        # call_number defaults to "1" — always comes from build_memory_context when available.
        # The call_count kwarg is kept for backward compatibility but is NOT used for
        # call_number when memory cannot be built (db=None or lead=None).
        call_number_str = "1"  # Default per REQ-2.4
        call_history = ""
        confirmed_facts = ""
        is_returning_caller_str = "false"

        # CAP-2: If db and lead are both provided, try to load real memory
        if db is not None and lead is not None:
            try:
                from app.memory import build_memory_context

                memory = await build_memory_context(db, lead)
                call_history = memory["call_history"]
                is_returning_caller_str = str(memory["is_returning_caller"]).lower()
                call_number_str = str(memory["call_number"])
                # Update returning_caller_context using real call_number
                if memory["call_number"] > 1:
                    returning_caller_context = RETURNING_CALLER_CONTEXT.format(
                        call_count=memory["call_number"]
                    )
            except Exception as exc:
                _structlog.error(
                    "memory_context_failed",
                    lead_id=getattr(lead, "id", None),
                    error_type=type(exc).__name__,
                    error_msg=str(exc),
                )
                # Keep empty defaults already set above

        return {
            "lead_name": lead_name,
            "broker_name": broker_name,
            "agent_name": agent_name,
            "car_make": car_make,
            "car_model": car_model,
            "car_year": car_year,
            "current_insurance": current_insurance,
            "returning_caller_context": returning_caller_context,
            # CAP-6/CAP-2: memory injection
            "call_history": call_history,
            "confirmed_facts": confirmed_facts,
            "is_returning_caller": is_returning_caller_str,
            "call_number": call_number_str,
        }

    @staticmethod
    def _sanitize_value(value: str) -> str:
        """Escape ``{{`` and ``}}`` in a variable value to prevent injection.

        Replaces ``{{`` → ``{ {`` and ``}}`` → ``} }`` so the value is treated
        as a literal string and cannot trigger further template substitutions.
        """
        return value.replace("{{", "{ {").replace("}}", "} }")

    async def _render_template(
        self,
        template: str,
        client: "Client",
        lead: "Lead | None",
        call_count: int,
        db: "AsyncSession | None" = None,
    ) -> str:
        """Substitute ``{{variable}}`` placeholders in *template*.

        All variable values are sanitised before substitution to prevent
        template injection via user-controlled data (design.md AD-6).

        CAP-2: Now async — awaits ``_build_variables`` which may call
        ``build_memory_context`` when ``db`` is provided.
        """
        variables = await self._build_variables(client, lead, call_count, db=db)
        sanitized = {k: self._sanitize_value(v) for k, v in variables.items()}

        def _replacer(match: re.Match) -> str:  # type: ignore[type-arg]
            key = match.group(1)
            return sanitized.get(key, match.group(0))  # leave unknown vars intact

        return re.sub(r"\{\{(\w+)\}\}", _replacer, template)

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Estimate token count using word count × 1.3 (design.md AD-4)."""
        return int(len(text.split()) * 1.3)

    def _truncate_knowledge(self, knowledge: str, *, client_id: str = "") -> str:
        """Truncate *knowledge* to ``MAX_KNOWLEDGE_TOKENS`` estimated tokens.

        Splits on whitespace and rejoins words until the token budget is used.
        Logs a warning when truncation occurs (spec CAP-2).

        Args:
            knowledge: Raw knowledge base text.
            client_id: Client slug, used only in the warning log message.

        Returns:
            Possibly-truncated knowledge text.
        """
        if self._estimate_tokens(knowledge) <= MAX_KNOWLEDGE_TOKENS:
            return knowledge

        # Truncate word-by-word to respect the token cap
        words = knowledge.split()
        # Each word ≈ 1.3 tokens → max words = MAX_KNOWLEDGE_TOKENS / 1.3
        max_words = int(MAX_KNOWLEDGE_TOKENS / 1.3)
        truncated = " ".join(words[:max_words])

        logger.warning(
            "knowledge truncated for client=%s: %d tokens → %d tokens (max %d)",
            client_id,
            self._estimate_tokens(knowledge),
            self._estimate_tokens(truncated),
            MAX_KNOWLEDGE_TOKENS,
        )
        return truncated
