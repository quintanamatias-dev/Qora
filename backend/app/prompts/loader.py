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

Covers: T1.2, T2.2, T2.3.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.tenants.models import Client
    from app.leads.models import Lead

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_KNOWLEDGE_TOKENS = 2000

# Default clients directory — resolved relative to this file so it works
# regardless of the working directory.  Tests override this via PromptLoader(clients_dir=…).
_DEFAULT_CLIENTS_DIR = Path(__file__).resolve().parents[3] / "clients"


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

    def load_prompt(self, client_id: str) -> str:
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
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        return JAUMPABLO_PROMPT_TEMPLATE

    def load_knowledge(self, client_id: str) -> str | None:
        """Return the knowledge base for *client_id*, or ``None``.

        Loads ``clients/{client_id}/knowledge.md``.  Returns ``None`` when the
        file (or directory) does not exist.

        Args:
            client_id: Client slug.

        Returns:
            Raw knowledge base content, or ``None`` if unavailable.
        """
        knowledge_path = self.clients_dir / client_id / "knowledge.md"
        if knowledge_path.exists():
            return knowledge_path.read_text(encoding="utf-8")
        return None

    def render(
        self,
        client: "Client",
        lead: "Lead | None" = None,
        call_count: int = 1,
    ) -> str:
        """Render the system prompt for *client* with optional *lead* context.

        Steps:
        1. Load prompt template (file or fallback).
        2. If template is the fallback hardcoded one, delegate to
           ``render_system_prompt`` from ``insurance_agent`` — it already
           handles variable substitution for the original ``{variable}``
           format.
        3. If template is from a file, build the variables dict, sanitise
           all values, then substitute ``{{variable}}`` placeholders via regex.
        4. Load ``knowledge.md``, truncate to ``MAX_KNOWLEDGE_TOKENS``, and
           append under ``## INFORMACIÓN DE LA EMPRESA``.

        Args:
            client: Client (tenant) ORM instance with ``id``, ``broker_name``,
                and ``agent_name``.
            lead: Optional lead ORM instance.  ``None`` uses safe defaults.
            call_count: Number of times the lead has been called (>1 = returning
                caller context).

        Returns:
            Fully rendered system prompt string.  No ``{{}}`` placeholders remain.
        """
        from app.prompts.insurance_agent import (
            JAUMPABLO_PROMPT_TEMPLATE,
            render_system_prompt,
        )

        client_id = client.id if client else "unknown"
        template = self.load_prompt(client_id)

        # ------------------------------------------------------------------
        # Render the prompt body
        # ------------------------------------------------------------------
        if template is JAUMPABLO_PROMPT_TEMPLATE:
            # Delegate to original renderer — handles the {single-brace} format
            prompt_body = render_system_prompt(client, lead, call_count)
        else:
            prompt_body = self._render_template(template, client, lead, call_count)

        # ------------------------------------------------------------------
        # Knowledge injection
        # ------------------------------------------------------------------
        knowledge = self.load_knowledge(client_id)
        if knowledge:
            knowledge = self._truncate_knowledge(knowledge, client_id=client_id)
            prompt_body = f"{prompt_body}\n\n## INFORMACIÓN DE LA EMPRESA\n{knowledge}"

        return prompt_body

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_variables(
        self,
        client: "Client",
        lead: "Lead | None",
        call_count: int,
    ) -> dict[str, str]:
        """Build the substitution dict from client + lead data."""
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

        return {
            "lead_name": lead_name,
            "broker_name": broker_name,
            "agent_name": agent_name,
            "car_make": car_make,
            "car_model": car_model,
            "car_year": car_year,
            "current_insurance": current_insurance,
            "returning_caller_context": returning_caller_context,
        }

    @staticmethod
    def _sanitize_value(value: str) -> str:
        """Escape ``{{`` and ``}}`` in a variable value to prevent injection.

        Replaces ``{{`` → ``{ {`` and ``}}`` → ``} }`` so the value is treated
        as a literal string and cannot trigger further template substitutions.
        """
        return value.replace("{{", "{ {").replace("}}", "} }")

    def _render_template(
        self,
        template: str,
        client: "Client",
        lead: "Lead | None",
        call_count: int,
    ) -> str:
        """Substitute ``{{variable}}`` placeholders in *template*.

        All variable values are sanitised before substitution to prevent
        template injection via user-controlled data (design.md AD-6).
        """
        variables = self._build_variables(client, lead, call_count)
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
