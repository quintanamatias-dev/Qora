# QORA — Cross-Call Memory System

## Overview

The QORA memory system injects accumulated knowledge about a lead into the system prompt at the start of every call. This allows the AI agent to behave as if it remembers the lead from previous conversations — referencing past call outcomes, known preferences, and operational notes — without requiring the LLM to retain state between sessions.

The canonical implementation is `backend/app/memory.py`.

## How Memory Is Injected

Memory context is injected via two paths:

1. **Initiation webhook** (`app/voice/initiation.py`): `build_memory_context()` runs inside the initiation handler. The resulting `call_history` and `confirmed_facts` strings are returned to ElevenLabs as `dynamic_variables` (the `type: "conversation_initiation_client_data"` response). ElevenLabs substitutes them into the agent's template via `{{call_history}}` / `{{confirmed_facts}}` before the first turn.

2. **Prompt loader** (`app/prompts/loader.py`): `PromptLoader.render_for_agent()` also calls `build_memory_context()` during per-turn system prompt rendering. This serves the Custom LLM webhook path (when the agent uses static prompts or no initiation webhook was called).

Memory context is assembled by `build_memory_context(db, lead)` and injected into the system prompt by `PromptLoader.render_for_agent()` via template variable substitution:

```
{{call_history}}      ← last 3 call summaries
{{confirmed_facts}}   ← extracted facts + misc notes + accumulated profile
```

Both variables are populated from `MemoryContext`:

```python
class MemoryContext(TypedDict):
    call_history: str        # multi-line string, one line per session
    confirmed_facts: str     # bulleted facts + notes + profile section
    is_returning_caller: bool
    call_number: int         # lead.call_count + 1
```

## `build_memory_context(db, lead)` — Function Contract

```python
async def build_memory_context(db: AsyncSession, lead: Lead) -> MemoryContext
```

**What it queries:**

1. **Any completed session?** (`SELECT 1 ... LIMIT 1`) — determines `is_returning_caller`. Completely independent of whether any session has a summary.

2. **Last 3 completed sessions with non-empty summaries** (newest first) — drives `call_history` formatting.

3. **All active `LeadProfileFact` rows** (`superseded_at IS NULL`) — drives the `--- Perfil acumulado ---` section.

4. **Last 5 `LeadInterestHistory` rows** — drives the `Evolución de interés: 75→60→85` line.

**Returns** a `MemoryContext` with:
- `call_history`: dated summary lines for the last 3 calls
- `confirmed_facts`: assembled from extracted_facts + misc_notes + accumulated profile
- `is_returning_caller`: `True` if **any** completed session exists (regardless of summary)
- `call_number`: `lead.call_count + 1` (the current call's number)

## What Gets Injected

### 1. Call History (`call_history`)

Up to the last **3** completed call summaries, formatted as:

```
Llamada del 15/04/2025: "El lead mostró interés en seguro de auto..."
Llamada del 22/04/2025: "El lead pidió llamar el martes con su esposa."
Llamada del 30/04/2025: "El lead confirmó interés y solicitó cotización."
```

Dates are displayed in `America/Argentina/Buenos_Aires` timezone (configurable per architecture decision AD-3).

Sessions without a summary are **excluded** from call history (but still count for `is_returning_caller`).

### 2. Confirmed Facts (`confirmed_facts`)

Assembled from three sources, in this order:

#### A. Scalar facts from `Lead.extracted_facts` (Tier 1 + Tier 2)

**Tier 1** — Known keys, fixed order, Spanish labels:
```
- Seguro actual: Mapfre
- Nivel de interés: 72/100
- Acción sugerida: follow_up
- Correcciones de datos: [...]
- Resumen: Mostró interés en seguro de vida...
```

**Tier 2** — Unknown/custom keys, alphabetical, raw key name as label:
```
- Call Outcome: completed_positive [high] — El lead aceptó cotización
- Detected Interests: productos=['auto'], needs=['nueva_cobertura']
- Identified Problem: costo (high) — seguros están subiendo de precio
```

Nested axis dicts are flattened to one-line summaries. `None`, empty strings, and empty lists are skipped.

**Keys that are always skipped**: `profile_facts` (rendered separately), `misc_notes` (rendered separately as its own section).

#### B. Operational Notes from `misc_notes` (dedicated section)

The `misc_notes` dimension produces a sliding-window set of operational notes injected as a separate section after the facts list:

```
--- Notas operativas ---
- [pending_topic] El lead quería comparar precios antes de decidir
- [temporary_context] Espera a su esposa para el martes
- [caution] Irritable si se lo interrumpe
```

Up to 5 notes, max 3 preferred. Notes are written in `analysis_language`. Notes about resolved/expired topics are dropped by the pipeline on each call.

#### C. Accumulated Profile from Relational Tables (dedicated section)

Profile facts and interest history from `LeadProfileFact` and `LeadInterestHistory`, injected as a final section:

```
--- Perfil acumulado ---
- Estilo de decisión: consulta con su esposa antes de tomar decisiones
- Disponibilidad: disponible solo los martes después de las 18hs
- Preferencia de contacto: prefiere WhatsApp sobre llamadas
- Señales de compra: preguntó por la prima mensual del plan Premium
- Evolución de interés: 30→55→72
```

Token budget: max 10 items per namespace. Namespaces rendered:
- `profile:` → Datos personales (grouped by category for structured facts)
- `pain:` → Puntos de dolor
- `service_issue:` → Problemas de servicio
- `signal:` → Señales de compromiso
- `buying_signal:` → Señales de compra

Interest history shows the last 5 data points in chronological order (oldest→newest).

## Memory Growth Over Multiple Calls

Each call adds to the memory in the following ways:

| After call N | Memory addition |
|-------------|-----------------|
| Call summary generated | Added to `CallSession.summary`; appears in `call_history` on call N+1 |
| Interest level computed | `Lead.interest_level` updated; `LeadInterestHistory` row appended |
| Profile facts extracted | `LeadProfileFact` rows added/updated/superseded |
| Misc notes updated | `Lead.extracted_facts["misc_notes"]` replaced with sliding window |
| Data corrections applied | `Lead` columns updated; `LeadProfileFact` rows for audit |
| `next_action` decided | `Lead.next_action`, `Lead.next_action_at` updated |

After 5+ calls, `build_memory_context()` will return:
- Up to 3 call summaries (most recent)
- The full accumulated interest history (up to 5 points)
- All active profile facts (grouped by category)
- Current operational notes (3–5 notes, freshly updated)

## Per-Session Context Cache

`build_memory_context()` is called **once per incoming webhook request** (not once per turn). The voice session stores the `system_prompt` generated at call start in the in-memory `ConversationState` and reuses it for all subsequent turns in that call. Memory is static within a call — it reflects the state at call start.

Session state is managed by `app/voice/session.py` (`session_store`). Sessions expire after 5 minutes of inactivity (TTL cleanup background task runs every 60 seconds).

## Architecture Decisions

| Decision | Description |
|----------|-------------|
| AD-1 | `build_memory_context` is at `app/memory.py` (top-level) — serves both the Custom LLM path (`prompts/loader.py`) and the Twilio/SIP path (`voice/initiation.py`) without circular imports |
| AD-2 | `MemoryContext` is a `TypedDict` so it merges into the variables dict via `{**vars, **memory}` |
| AD-3 | Dates are converted to `America/Argentina/Buenos_Aires` timezone before formatting (hardcoded; could be per-client in the future) |
| AD-6 | `confirmed_facts` Tier 1 key ordering is fixed by code (`_KNOWN_FACTS` list), not dict iteration order |
