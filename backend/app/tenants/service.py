"""QORA Tenants — Service layer for Client CRUD, Agent CRUD, and seed operations."""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.tenants.models import Agent, Client


async def create_client(
    session: AsyncSession,
    *,
    id: str,
    name: str,
    broker_name: str,
    agent_name: str = "Jaumpablo",
    voice_id: str,
    system_prompt_override: str | None = None,
    knowledge_base: str | None = None,
    model: str = "gpt-4o",
    temperature: float = 0.7,
    max_tokens: int = 300,
    tools_enabled: str = '["get_lead_details","register_interest","mark_not_interested","schedule_followup"]',
    is_active: bool = True,
    # Scheduler configuration (Phase 7 — bootstrappable at create time)
    scheduler_enabled: bool = False,
    scheduler_max_attempts: int = 3,
    scheduler_cooldown_minutes: int = 60,
    scheduler_allowed_hours_start: int = 9,
    scheduler_allowed_hours_end: int = 20,
    scheduler_retry_on_outcomes: str = '["call_again","follow_up"]',
    scheduler_timezone: str = "America/Argentina/Buenos_Aires",
    # Issue #35 — Per-client extraction configuration (JSON string or None)
    extraction_config: str | None = None,
) -> Client:
    """Create and persist a new Client record and its default Agent.

    Automatically creates a default Agent for the new client, copying agent
    configuration fields (agent_name → name, voice_id, model, temperature,
    max_tokens, tools_enabled, system_prompt_override → system_prompt, knowledge_base).

    Args:
        session: Active async DB session.
        id: Human-readable slug (e.g., "quintana-seguros").
        name: Display name (must be unique).
        broker_name: Name of the broker company.
        agent_name: Name of the AI agent.
        voice_id: ElevenLabs voice ID.
        ...

    Returns:
        The persisted Client instance.
    """
    client = Client(
        id=id,
        name=name,
        broker_name=broker_name,
        agent_name=agent_name,
        voice_id=voice_id,
        system_prompt_override=system_prompt_override,
        knowledge_base=knowledge_base,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        tools_enabled=tools_enabled,
        is_active=is_active,
        scheduler_enabled=scheduler_enabled,
        scheduler_max_attempts=scheduler_max_attempts,
        scheduler_cooldown_minutes=scheduler_cooldown_minutes,
        scheduler_allowed_hours_start=scheduler_allowed_hours_start,
        scheduler_allowed_hours_end=scheduler_allowed_hours_end,
        scheduler_retry_on_outcomes=scheduler_retry_on_outcomes,
        scheduler_timezone=scheduler_timezone,
        extraction_config=extraction_config,
    )
    session.add(client)
    await session.flush()  # Flush to DB within current transaction

    # Bootstrap a default Agent for this client (CRITICAL 1b: every client must have one)
    # Sanitize slug: lowercase, keep only [a-z0-9-], collapse consecutive hyphens,
    # strip leading/trailing hyphens so the slug passes the _SLUG_RE validation.
    raw_slug = (agent_name or "agent").lower()
    raw_slug = re.sub(r"[^a-z0-9-]", "-", raw_slug)  # replace invalid chars with hyphen
    raw_slug = re.sub(r"-+", "-", raw_slug)  # collapse consecutive hyphens
    raw_slug = raw_slug.strip("-")  # strip leading/trailing hyphens
    slug = raw_slug or "agent"  # fallback if empty after sanitization

    await create_agent(
        session,
        client_id=id,
        slug=slug,
        name=agent_name,
        voice_id=voice_id,
        system_prompt=system_prompt_override,
        knowledge_base=knowledge_base,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        tools_enabled=tools_enabled,
        is_active=True,
        is_default=True,
    )

    return client


async def get_client(session: AsyncSession, client_id: str) -> Client | None:
    """Fetch a Client by its id slug.

    Returns:
        Client instance or None if not found.
    """
    result = await session.execute(select(Client).where(Client.id == client_id))
    return result.scalar_one_or_none()


async def get_client_by_name(session: AsyncSession, name: str) -> Client | None:
    """Fetch a Client by its unique display name.

    Returns:
        Client instance or None if not found.
    """
    result = await session.execute(select(Client).where(Client.name == name))
    return result.scalar_one_or_none()


async def update_client(
    session: AsyncSession,
    client_id: str,
    **kwargs,
) -> Client | None:
    """Update fields on an existing Client record.

    Args:
        session: Active async DB session.
        client_id: The id of the client to update.
        **kwargs: Fields to update (e.g., name="New Name", broker_name="New Broker").

    Returns:
        Updated Client instance or None if client not found.
    """
    client = await get_client(session, client_id)
    if client is None:
        return None

    for key, value in kwargs.items():
        if hasattr(client, key):
            setattr(client, key, value)

    await session.flush()
    return client


# ---------------------------------------------------------------------------
# Quintana Seguros — Prompt seed constants (AD-1)
# The canonical agent prompt now lives at:
#   backend/clients/quintana-seguros/agents/jaumpablo/system-prompt.md
# That filesystem file is the source of truth (loaded by PromptLoader.render_for_agent).
# These DB constants remain as a legacy seed/fallback — used by seed_quintana() to
# populate agent.system_prompt when no filesystem file existed previously.
# ---------------------------------------------------------------------------

_QUINTANA_SYSTEM_PROMPT = """\
Sos {{agent_name}}, asesor de seguros de {{broker_name}}, una correduría argentina.
Hablás siempre en español rioplatense con voseo natural. Sos cálido, directo y genuino — como ese vendedor que te cae bien y te convence porque es honesto, no porque te presiona.

Tu trabajo es VENDER. Conducís la conversación activamente. No esperás que el cliente te pregunte — vos preguntás, proponés y cerrás.

════════════════════════════════════════════════════
DATOS DEL LEAD — LOS SABÉS DE ANTEMANO
════════════════════════════════════════════════════

Nombre: {{lead_name}}
Auto: {{car_make}} {{car_model}} {{car_year}}
Seguro actual: {{current_insurance}}
Este es el llamado número {{call_number}} a este lead.
Lead recurrente: {{is_returning_caller}} (true = ya hablaron antes, false = primer contacto).

{{confirmed_facts}}

{{call_history}}
Este lead dejó sus datos porque quería una cotización. Te está esperando.

════════════════════════════════════════════════════
MEMORIA DE CONVERSACIONES ANTERIORES — PRIORIDAD MÁXIMA
════════════════════════════════════════════════════

Si la información de {{confirmed_facts}} contradice los DATOS DEL LEAD de arriba
(por ejemplo, el lead te dijo que su auto es otro modelo o marca), SIEMPRE priorizá
lo que el lead te dijo directamente — es información más reciente y confiable.

NUNCA repitas datos que el lead ya corrigió. Usá la versión actualizada.
Si {{confirmed_facts}} está vacío, tomá los DATOS DEL LEAD como referencia.

════════════════════════════════════════════════════
CÓMO MANEJÁS LA CONVERSACIÓN
════════════════════════════════════════════════════

VOS CONDUCÍS. Hacés preguntas cortas y concretas. Una por vez.
Después de cada respuesta del cliente, avanzás al siguiente paso — no esperás que él te guíe.

PASO 1 — APERTURA (ya hecho por el primer mensaje del agente)
El agente ya se presentó con "¡Hola {{lead_name}}! ¿Hablo con {{lead_name}}?"
Cuando confirme que es él, INMEDIATAMENTE presentate y pasá al PASO 2.

Si {{call_number}} es 1 (primera llamada):
Ejemplo: "Buenísimo {{lead_name}}! Soy {{agent_name}} de {{broker_name}}. Te llamo porque dejaste tus datos para cotizar el seguro de tu {{car_make}} {{car_model}}. ¿Tenés un minuto para que te cuente?"

Si {{call_number}} es mayor a 1 (llamada de seguimiento):
Recordá que ya hablaron antes — hacé referencia a eso naturalmente.
Ejemplo: "¡Hola {{lead_name}}! Soy {{agent_name}} de {{broker_name}}, te vuelvo a llamar por lo del seguro de tu {{car_make}} {{car_model}} que hablamos antes. ¿Pudiste pensarlo?"
Usá la información de {{call_history}} para personalizar la conversación: recordá objeciones previas, retomá donde se quedaron, no repitas preguntas ya respondidas.

PASO 2 — CALIFICACIÓN RÁPIDA
Confirmá que sigue teniendo el auto y el uso. Una sola pregunta:
"¿Lo usás para uso particular o también para trabajo?"

PASO 3 — SEGURO ACTUAL (punto de dolor)
Preguntá directamente: "¿Tenés seguro ahora o te quedaste sin cobertura?"
Si tiene seguro: "¿Y estás conforme con lo que pagás?"
Si no tiene: "Ah, entonces estás manejando sin cobertura — eso es arriesgado, {{lead_name}}."

PASO 4 — PROPUESTA (sin inventar precios)
Presentá el valor, no el precio:
"Mirá, lo que hacemos en {{broker_name}} es buscar la mejor cobertura para tu auto específico.
No te damos un número genérico — te hacemos una cotización a medida, sin compromiso."
Beneficios a mencionar: atención personalizada, respaldo ante siniestros, precio competitivo.
NUNCA inventés precios ni porcentajes. Decís "cotización a medida".

PASO 5 — CIERRE ACTIVO
No preguntés "¿te interesa?" — asumí el interés y avanzá:
"Bueno {{lead_name}}, ¿te mando la cotización al mail o preferís que te llame con los números?"
Si acepta → llamá a register_interest
Si pone objeciones → manejo (ver abajo)
Si dice que no claramente → llamá a mark_not_interested con la razón

════════════════════════════════════════════════════
MANEJO DE OBJECIONES — RESPUESTAS CONCRETAS
════════════════════════════════════════════════════

"Es caro / No tengo plata":
→ "Entiendo. Por eso hacemos la cotización — para ver si podemos mejorar lo que estás pagando ahora. ¿Le damos una chance?"

"Ya tengo seguro":
→ "Perfecto, eso está bien. ¿Y estás conforme con el precio que pagás? Porque a veces conviene comparar."

"No me interesa":
→ "Dale, te entiendo. ¿Puedo preguntarte por qué? Así mejoramos."
→ Si sigue sin interés: llamá a mark_not_interested

"Ahora no puedo / Estoy ocupado":
→ "Sin problema. ¿Cuándo te llamo mejor, mañana a la mañana o a la tarde?"
→ Llamá a schedule_followup con la fecha que diga

"Lo tengo que pensar":
→ "Claro, es una decisión. ¿Qué es lo que te genera dudas? A lo mejor te puedo dar más info ahora."

════════════════════════════════════════════════════
REGLAS DE HERRAMIENTAS
════════════════════════════════════════════════════

- register_interest: Cuando el lead acepta recibir cotización o muestra interés claro
- mark_not_interested: Cuando rechaza claramente, después de intentar al menos una objeción
- schedule_followup: Cuando pide ser llamado en otro momento — siempre confirmá la fecha
- get_lead_details: Solo si necesitás más datos que no tenés

Después de usar una herramienta: "Perfecto {{lead_name}}, ya quedó registrado. [continuá naturalmente]"

════════════════════════════════════════════════════
RESTRICCIONES ABSOLUTAS
════════════════════════════════════════════════════

- NUNCA inventés precios, coberturas específicas ni porcentajes
- NUNCA presionés después de un "no" claro — respetá y cerrá con amabilidad
- NUNCA uses "tú" — siempre "vos"
- NUNCA hagas más de una pregunta por turno
- SIEMPRE terminá la llamada con amabilidad, aunque rechacen\
"""

_QUINTANA_KNOWLEDGE_BASE = """\
# Quintana Seguros — Información de la Empresa

## Coberturas disponibles

- **Responsabilidad Civil**: Cobertura básica obligatoria, protege ante daños a terceros
- **Terceros Completo**: RC + robo total e incendio total
- **Todo Riesgo**: Cobertura completa con franquicia, incluye daños propios

## Ventajas de Quintana Seguros

- 20 años en el mercado argentino con trayectoria comprobada
- Atención personalizada 24/7 ante siniestros
- Proceso de cotización en menos de 24 horas
- Sin letra chica — todo claro desde el primer día
- Trabajamos con más de 5 aseguradoras líderes: Zurich, La Caja, Meridional, Sancor, HDI

## Proceso de cotización

1. Recibimos los datos del vehículo (marca, modelo, año, uso)
2. Consultamos con 5+ aseguradoras de forma simultánea
3. Seleccionamos las 3 mejores opciones según precio y cobertura
4. Te enviamos el comparativo en menos de 24hs
5. Vos elegís — sin presión, sin compromiso

## Preguntas frecuentes

**¿Atienden accidentes a cualquier hora?**
Sí, línea de asistencia 24/7 todos los días del año.

**¿Puedo cambiar de cobertura después de contratar?**
Sí, podés ajustar tu cobertura en cualquier momento sin penalidades.

**¿Trabajan con autos usados?**
Sí, cotizamos para autos de cualquier año, incluso modelos más antiguos.

**¿Cuánto tarda el pago ante un siniestro?**
Depende de la aseguradora, pero gestionamos para que sea lo más ágil posible, en promedio 15 días hábiles.\
"""


async def seed_quintana(session: AsyncSession) -> None:
    """Seed the Quintana Seguros client if it does not already exist.

    Idempotent: calling this multiple times has no effect if the record exists
    and both prompt/knowledge fields are already populated.

    AD-1: Prompt and knowledge content is embedded as string constants (_QUINTANA_SYSTEM_PROMPT,
    _QUINTANA_KNOWLEDGE_BASE) as a legacy DB seed/fallback. The canonical source of truth is
    the filesystem: backend/clients/quintana-seguros/agents/jaumpablo/system-prompt.md.
    PromptLoader.render_for_agent() prefers the filesystem file over the DB prompt.

    AD-2: Non-overwrite guard — only updates agent fields when they are missing or blank
    (None or empty string). Protects runtime edits made via admin UI.
    """
    existing = await get_client(session, "quintana-seguros")
    if existing is not None:
        # AD-2: One-time migration guard — populate agent fields only when missing or blank
        agent = await get_default_agent(session, "quintana-seguros")
        if agent is not None:
            updated = False
            if not agent.system_prompt:
                agent.system_prompt = _QUINTANA_SYSTEM_PROMPT
                updated = True
            if not agent.knowledge_base:
                agent.knowledge_base = _QUINTANA_KNOWLEDGE_BASE
                updated = True
            if updated:
                await session.flush()
        return  # Already seeded — skip client creation

    await create_client(
        session,
        id="quintana-seguros",
        name="Quintana Seguros",
        broker_name="Quintana Seguros",
        agent_name="Jaumpablo",
        voice_id="pNInz6obpgDQGcFmaJgB",
        model="gpt-4o",
        temperature=0.7,
        max_tokens=300,
        tools_enabled='["get_lead_details","register_interest","mark_not_interested","schedule_followup"]',
        system_prompt_override=_QUINTANA_SYSTEM_PROMPT,
        knowledge_base=_QUINTANA_KNOWLEDGE_BASE,
    )
    # Note: create_client() auto-creates the default Agent — no separate create_agent() needed.


_QORA_EXPLAINER_SYSTEM_PROMPT = """\
Sos Sofia, la asistente virtual de la plataforma Qora. Qora es una solución de inteligencia \
artificial para equipos de ventas de seguros que automatiza llamadas de seguimiento, califica \
leads y agenda entrevistas — todo en el idioma del cliente y con voz natural.

Tu objetivo es explicar Qora de manera clara y entusiasta: qué hace, cómo funciona y por qué \
los productores de seguros la eligen. Respondé preguntas sobre integraciones, precios y casos \
de uso. Invitá al prospecto a agendar una demo con el equipo comercial cuando muestre interés.

Hablá siempre en el idioma del prospecto. Sé concisa, cálida y profesional.\
"""

# Sofia voice on ElevenLabs — configure EL agent in dashboard, not via voice_id override
_QORA_DEMO_VOICE_ID = "ByVRQtaK1WDOvTmP1PKO"


async def seed_qora_demo(session: AsyncSession) -> None:
    """Seed the Qora Demo client + qora-explainer agent + demo lead if they don't exist.

    Idempotent: calling this multiple times has no effect if the records exist.
    The canonical agent prompt is the filesystem file:
        backend/clients/qora-demo/agents/qora-explainer/system-prompt.md
    The DB system_prompt seeded here is a legacy fallback — PromptLoader.render_for_agent()
    prefers the filesystem file when it exists.
    The agent slug is 'qora-explainer'; voice is configured via ElevenLabs dashboard.
    Sets elevenlabs_agent_id from Settings.elevenlabs_agent_id if configured.
    Seeded lead: Demo Visitor — used by the demo page conversation flow.
    """
    from app.core.config import Settings

    settings = Settings()

    existing = await get_client(session, "qora-demo")
    if existing is None:
        # create_client() auto-creates a default agent; we override it with the correct
        # agent name and system_prompt via system_prompt_override on create_client.
        await create_client(
            session,
            id="qora-demo",
            name="qora-demo",
            broker_name="Qora Demo",
            agent_name="qora-explainer",
            voice_id=_QORA_DEMO_VOICE_ID,
            system_prompt_override=_QORA_EXPLAINER_SYSTEM_PROMPT,
            model="gpt-4o",
            temperature=0.7,
            max_tokens=400,
            tools_enabled="[]",
        )
        # Note: create_client() auto-creates the default Agent with the correct name and
        # system_prompt (passed via system_prompt_override → system_prompt on Agent).

        # Set elevenlabs_agent_id from settings if configured
        if settings.elevenlabs_agent_id:
            agent = await get_default_agent(session, "qora-demo")
            if agent is not None:
                agent.elevenlabs_agent_id = settings.elevenlabs_agent_id
                await session.flush()

    # Idempotently seed the Demo Visitor lead for qora-demo
    from app.leads.service import list_leads_for_client, create_lead

    existing_leads = await list_leads_for_client(session, "qora-demo")
    if not existing_leads:
        await create_lead(
            session,
            client_id="qora-demo",
            name="Demo Visitor",
            phone="+10000000000",
            notes="Demo lead — used by Qora demo page conversation flow",
        )


# ---------------------------------------------------------------------------
# Agent CRUD
# ---------------------------------------------------------------------------


async def create_agent(
    session: AsyncSession,
    *,
    client_id: str,
    slug: str,
    name: str,
    voice_id: str,
    system_prompt: str | None = None,
    knowledge_base: str | None = None,
    model: str = "gpt-4o",
    temperature: float = 0.7,
    max_tokens: int = 300,
    tools_enabled: str = '["get_lead_details","register_interest","mark_not_interested","schedule_followup"]',
    is_active: bool = True,
    is_default: bool = False,
    elevenlabs_agent_id: str | None = None,
) -> Agent:
    """Create and persist a new Agent record.

    Enforces that at most one Agent per client has is_default=True.

    Args:
        session: Active async DB session.
        client_id: Foreign key to the owning Client.
        slug: URL-friendly identifier (unique per client).
        name: Display name for the agent.
        voice_id: ElevenLabs voice ID.
        ...

    Returns:
        The persisted Agent instance.

    Raises:
        ValueError: If is_default=True and another default already exists for this client.
    """
    if is_default:
        existing_default = await get_default_agent(session, client_id)
        if existing_default is not None:
            raise ValueError(
                f"Client {client_id!r} already has a default agent: {existing_default.id!r}. "
                "Only one agent per client may have is_default=True."
            )

    # Validate slug uniqueness per client (before DB flush to give a clean error)
    existing_slug = await session.execute(
        select(Agent).where(
            Agent.client_id == client_id,
            Agent.slug == slug,
        )
    )
    if existing_slug.scalar_one_or_none() is not None:
        raise ValueError(
            f"Agent with slug {slug!r} already exists for client {client_id!r}. "
            "slug must be unique per client."
        )

    agent = Agent(
        id=str(uuid.uuid4()),
        client_id=client_id,
        slug=slug,
        name=name,
        voice_id=voice_id,
        system_prompt=system_prompt,
        knowledge_base=knowledge_base,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        tools_enabled=tools_enabled,
        is_active=is_active,
        is_default=is_default,
        elevenlabs_agent_id=elevenlabs_agent_id,
    )
    session.add(agent)
    await session.flush()
    return agent


async def get_agent(session: AsyncSession, agent_id: str) -> Agent | None:
    """Fetch an Agent by its UUID id.

    Returns:
        Agent instance or None if not found.
    """
    result = await session.execute(select(Agent).where(Agent.id == agent_id))
    return result.scalar_one_or_none()


async def get_default_agent(session: AsyncSession, client_id: str) -> Agent | None:
    """Fetch the default Agent for a client.

    Returns:
        The active Agent with is_default=True for the given client_id, or None.
        Deactivated agents are excluded even if they have is_default=True.
    """
    result = await session.execute(
        select(Agent).where(
            Agent.client_id == client_id,
            Agent.is_default == True,  # noqa: E712
            Agent.is_active == True,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# New Agent service functions (Phase 7)
# ---------------------------------------------------------------------------


async def list_agents_for_client(
    session: AsyncSession,
    client_id: str,
    *,
    include_inactive: bool = False,
) -> list[Agent]:
    """Return all agents for a client ordered by created_at ascending.

    Args:
        session: Active async DB session.
        client_id: The client to query agents for.
        include_inactive: When False (default), only active agents are returned.

    Returns:
        List of Agent instances sorted by created_at ascending.
    """
    from sqlalchemy import asc

    conditions = [Agent.client_id == client_id]
    if not include_inactive:
        conditions.append(Agent.is_active == True)  # noqa: E712

    result = await session.execute(
        select(Agent).where(*conditions).order_by(asc(Agent.created_at))
    )
    return list(result.scalars().all())


async def update_agent(
    session: AsyncSession,
    agent_id: str,
    client_id: str,
    **kwargs: object,
) -> Agent | None:
    """Partially update an Agent record. Only provided kwargs are written.

    Enforces client isolation: returns None if the agent_id belongs to a
    different client than client_id.

    Args:
        session: Active async DB session.
        agent_id: UUID of the agent to update.
        client_id: The owning client (used for cross-client isolation check).
        **kwargs: Fields to update (e.g., name="New Name", temperature=0.9).

    Returns:
        Updated Agent instance or None if not found / wrong client.
    """
    result = await session.execute(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.client_id == client_id,
        )
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        return None

    for key, value in kwargs.items():
        if hasattr(agent, key):
            setattr(agent, key, value)

    await session.flush()
    return agent


async def deactivate_agent(
    session: AsyncSession,
    agent_id: str,
    client_id: str,
) -> Agent:
    """Soft-delete an agent by setting is_active=False.

    GUARD: Raises ValueError if the agent is the sole active default agent for
    its client. A client must always have at least one active default agent.

    Args:
        session: Active async DB session.
        agent_id: UUID of the agent to deactivate.
        client_id: Owning client (for isolation check).

    Returns:
        The updated Agent with is_active=False.

    Raises:
        ValueError: If agent not found, or if it is the sole active default.
    """
    result = await session.execute(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.client_id == client_id,
        )
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise ValueError(f"Agent {agent_id!r} not found for client {client_id!r}.")

    # Sole-default guard: if this agent is the ONLY active default, block deactivation
    if agent.is_default and agent.is_active:
        active_defaults_result = await session.execute(
            select(Agent).where(
                Agent.client_id == client_id,
                Agent.is_default == True,  # noqa: E712
                Agent.is_active == True,  # noqa: E712
            )
        )
        active_defaults = list(active_defaults_result.scalars().all())
        if len(active_defaults) <= 1:
            raise ValueError(
                f"cannot_deactivate_sole_default_agent: agent {agent_id!r} is the "
                f"only active default for client {client_id!r}."
            )

    agent.is_active = False
    await session.flush()
    return agent


async def set_default_agent(
    session: AsyncSession,
    client_id: str,
    agent_id: str,
) -> Agent:
    """Atomically swap the default agent for a client.

    Unsets is_default on all other agents for the client, then sets is_default
    on the target agent. Both writes happen in a single flush (same transaction).

    Args:
        session: Active async DB session.
        client_id: The owning client.
        agent_id: UUID of the agent to make default.

    Returns:
        The updated Agent with is_default=True.

    Raises:
        ValueError: If agent not found or agent is inactive.
    """
    from sqlalchemy import update as sa_update

    # Fetch the target agent with client isolation
    result = await session.execute(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.client_id == client_id,
        )
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise ValueError(f"Agent {agent_id!r} not found for client {client_id!r}.")

    if not agent.is_active:
        raise ValueError(
            f"cannot_set_inactive_agent_as_default: agent {agent_id!r} is inactive."
        )

    # Unset all other defaults for this client in one UPDATE
    await session.execute(
        sa_update(Agent)
        .where(
            Agent.client_id == client_id,
            Agent.id != agent_id,
        )
        .values(is_default=False)
    )

    # Set this agent as default
    agent.is_default = True
    await session.flush()
    return agent
