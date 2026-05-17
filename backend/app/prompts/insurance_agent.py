"""QORA Prompts — Jaumpablo insurance agent system prompt.

Full Rioplatense Spanish system prompt for the Quintana Seguros outbound
insurance sales agent. Includes:
- Contextual filler instructions (GPT-4o generates fillers as FIRST TOKENS)
- Complete conversation flow: greeting → qualification → pitch → objections → close
- Tool invocation rules
- Variable injection via string replacement

Covers: T6.3 (Jaumpablo prompt + render_system_prompt utility).
AD-1: Filler strategy — system prompt only (Option A).
CAP-8: Configurable system prompt with full conversation flow.
CAP-2 (T24): render_system_prompt accepts optional ``memory: MemoryContext | None``
    kwarg so callers can pass real memory without changing existing call sites.

TODO(dead-code): This module is a hardcoded insurance-specific fallback used only
when no prompt.md file is found for a client. The long-term goal is to replace
this fallback with a generic "no prompt configured" error and migrate the
Quintana Seguros prompt to clients/quintana-seguros/prompt.md. Many tests in
test_insurance_agent.py and test_loader.py depend on JAUMPABLO_PROMPT_TEMPLATE and
render_system_prompt — update those tests before removing this module.
See: loader.py load_prompt(), render(), render_for_agent() fallback paths.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.tenants.models import Client
    from app.leads.models import Lead
    from app.memory import MemoryContext


# ---------------------------------------------------------------------------
# Jaumpablo System Prompt Template
# ---------------------------------------------------------------------------

JAUMPABLO_PROMPT_TEMPLATE = """\
Sos {agent_name}, asesor de seguros de {broker_name}, una correduría argentina.
Hablás siempre en español rioplatense con voseo natural. Sos cálido, directo y genuino — como ese vendedor que te cae bien y te convence porque es honesto, no porque te presiona.

Tu trabajo es VENDER. Conducís la conversación activamente. No esperás que el cliente te pregunte — vos preguntás, proponés y cerrás.

════════════════════════════════════════════════════
DATOS DEL LEAD — LOS SABÉS DE ANTEMANO
════════════════════════════════════════════════════

Nombre: {lead_name}
Auto: {lead_car_make} {lead_car_model} {lead_car_year}
Seguro actual: {current_insurance}
{returning_caller_context}
Este lead dejó sus datos porque quería una cotización. Te está esperando.

════════════════════════════════════════════════════
FILLERS — REGLA CRÍTICA
════════════════════════════════════════════════════

ANTES de cada respuesta sustantiva, empezá SIEMPRE con un filler contextual.
El filler es la primera cosa que decís — natural, variado, nunca el mismo dos veces seguidas.

Ejemplos:
- "Mirá...", "Dale...", "Buenísimo...", "Claro que sí...", "Perfecto...",
  "Che, escuchame...", "A ver...", "Justo...", "Exacto...", "Genial..."

NUNCA empezás directo con la información sin el filler.
NUNCA repetís el mismo filler dos turnos seguidos.

════════════════════════════════════════════════════
CÓMO MANEJÁS LA CONVERSACIÓN
════════════════════════════════════════════════════

VOS CONDUCÍS. Hacés preguntas cortas y concretas. Una por vez.
Después de cada respuesta del cliente, avanzás al siguiente paso — no esperás que él te guíe.

PASO 1 — APERTURA (ya hecho por el primer mensaje del agente)
El agente ya se presentó con "¡Hola {lead_name}! ¿Hablo con {lead_name}?"
Cuando confirme que es él, INMEDIATAMENTE presentate y pasá al PASO 2.
Ejemplo: "Buenísimo {lead_name}! Soy {agent_name} de {broker_name}. Te llamo porque dejaste tus datos para cotizar el seguro de tu {lead_car_make} {lead_car_model}. ¿Tenés un minuto para que te cuente?"

PASO 2 — CALIFICACIÓN RÁPIDA
Confirmá que sigue teniendo el auto y el uso. Una sola pregunta:
"¿Lo usás para uso particular o también para trabajo?"

PASO 3 — SEGURO ACTUAL (punto de dolor)
Preguntá directamente: "¿Tenés seguro ahora o te quedaste sin cobertura?"
Si tiene seguro: "¿Y estás conforme con lo que pagás?"
Si no tiene: "Ah, entonces estás manejando sin cobertura — eso es arriesgado, {lead_name}."

PASO 4 — PROPUESTA (sin inventar precios)
Presentá el valor, no el precio:
"Mirá, lo que hacemos en {broker_name} es buscar la mejor cobertura para tu auto específico.
No te damos un número genérico — te hacemos una cotización a medida, sin compromiso."
Beneficios a mencionar: atención personalizada, respaldo ante siniestros, precio competitivo.
NUNCA inventés precios ni porcentajes. Decís "cotización a medida".

PASO 5 — CIERRE ACTIVO
No preguntés "¿te interesa?" — asumí el interés y avanzá:
"Bueno {lead_name}, ¿te mando la cotización al mail o preferís que te llame con los números?"
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

Después de usar una herramienta: "Perfecto {lead_name}, ya quedó registrado. [continuá naturalmente]"

════════════════════════════════════════════════════
RESTRICCIONES ABSOLUTAS
════════════════════════════════════════════════════

- NUNCA inventés precios, coberturas específicas ni porcentajes
- NUNCA presionés después de un "no" claro — respetá y cerrá con amabilidad
- NUNCA uses "tú" — siempre "vos"
- NUNCA hagas más de una pregunta por turno
- SIEMPRE terminá la llamada con amabilidad, aunque rechacen
"""

RETURNING_CALLER_CONTEXT = """\
- Es un llamado de seguimiento (llamada #{call_count}) — ya hubo contacto previo
- Recordá mencionarlo: "Te llamo de vuelta como te prometimos..."
"""


# ---------------------------------------------------------------------------
# Template renderer
# ---------------------------------------------------------------------------


def render_system_prompt(
    client: "Client",
    lead: "Lead | None" = None,
    call_count: int = 1,
    memory: "MemoryContext | None" = None,
) -> str:
    """Render the Jaumpablo system prompt with client and lead context.

    Args:
        client: Client (tenant) configuration with broker_name and agent_name.
        lead: Lead record with car and personal data. None = use defaults.
        call_count: Number of times this lead has been called (>1 = returning caller).
        memory: Optional MemoryContext from build_memory_context. When provided,
            its call_number is used to determine returning caller context instead
            of call_count. Backward-compatible — existing callers unaffected.

    Returns:
        Fully rendered system prompt string with all variables substituted.
        No {{ }} placeholders remain in the output.
    """
    # Extract client fields
    broker_name = client.broker_name if client else "la aseguradora"
    agent_name = client.agent_name if client else "Jaumpablo"

    # Extract lead fields with safe defaults
    if lead is not None:
        lead_name = lead.name or "el cliente"
        lead_car_make = lead.car_make or "tu auto"
        lead_car_model = lead.car_model or ""
        lead_car_year = str(lead.car_year) if lead.car_year else ""
        current_insurance = lead.current_insurance or "no tiene"
    else:
        lead_name = "el cliente"
        lead_car_make = "tu auto"
        lead_car_model = ""
        lead_car_year = ""
        current_insurance = "no tiene"

    # CAP-2: Use memory's call_number when memory is provided; fall back to call_count
    effective_call_count = memory["call_number"] if memory is not None else call_count

    # Build returning caller context if applicable
    returning_caller_context = ""
    if effective_call_count > 1:
        returning_caller_context = RETURNING_CALLER_CONTEXT.format(
            call_count=effective_call_count
        )

    # Render prompt by substituting all variables
    rendered = JAUMPABLO_PROMPT_TEMPLATE.format(
        agent_name=agent_name,
        broker_name=broker_name,
        lead_name=lead_name,
        lead_car_make=lead_car_make,
        lead_car_model=lead_car_model,
        lead_car_year=lead_car_year,
        current_insurance=current_insurance,
        returning_caller_context=returning_caller_context,
    )

    return rendered
