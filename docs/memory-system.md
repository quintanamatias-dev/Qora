# Cross-Call Memory System

The Qora memory system injects accumulated knowledge about a lead into the system prompt at the start of every call. This lets the AI agent behave as if it remembers the lead from previous conversations — referencing past call outcomes, known preferences, and operational notes — without requiring the LLM to retain state between sessions. Memory is **static within a call**: it reflects the state at call start and is not updated mid-conversation.

The canonical implementation is `backend/app/memory.py`.

---

## TL;DR

| What gets remembered | Where it's stored | How it reaches the agent |
|----------------------|-------------------|--------------------------|
| Last 3 call summaries | `CallSession.summary` | `{{call_history}}` template variable |
| Scalar facts (interest level, outcome, etc.) | `Lead.extracted_facts` | `{{confirmed_facts}}` template variable |
| Operational notes (sliding window) | `Lead.extracted_facts["misc_notes"]` | `{{confirmed_facts}}` — `--- Notas operativas ---` section |
| Stable profile traits | `LeadProfileFact` table | `{{confirmed_facts}}` — `--- Perfil acumulado ---` section |
| Interest score history | `LeadInterestHistory` table | `{{confirmed_facts}}` — `Evolución de interés` line |

---

## How Memory Is Injected

Memory context flows into the system prompt through two paths:

**Path 1 — Initiation webhook** (`app/voice/initiation.py`)
`build_memory_context()` runs inside the initiation handler. The resulting strings are returned to ElevenLabs as `dynamic_variables` (the `type: "conversation_initiation_client_data"` response). ElevenLabs substitutes them into the agent's template before the first turn.

**Path 2 — Prompt loader** (`app/prompts/loader.py`)
`PromptLoader.render_for_agent()` also calls `build_memory_context()` during per-turn system prompt rendering. This serves the Custom LLM webhook path when no initiation webhook was called.

Both paths inject two template variables:

```
{{call_history}}      ← last 3 call summaries
{{confirmed_facts}}   ← extracted facts + misc notes + accumulated profile
```

### `MemoryContext` object

```python
class MemoryContext(TypedDict):
    call_history: str        # multi-line string, one line per session
    confirmed_facts: str     # bulleted facts + notes + profile section
    is_returning_caller: bool
    call_number: int         # lead.call_count + 1
```

---

## `build_memory_context(db, lead)`

```python
async def build_memory_context(db: AsyncSession, lead: Lead) -> MemoryContext
```

**Queries executed**:

| Query | Purpose |
|-------|---------|
| `SELECT 1 FROM call_sessions … LIMIT 1` | Determines `is_returning_caller` — independent of whether any session has a summary |
| Last 3 completed sessions with non-empty summaries (newest first) | Drives `call_history` formatting |
| All active `LeadProfileFact` rows (`superseded_at IS NULL`) | Drives `--- Perfil acumulado ---` section |
| Last 5 `LeadInterestHistory` rows | Drives `Evolución de interés: 75→60→85` line |

---

## What Gets Injected

### 1. Call History (`{{call_history}}`)

Up to the last **3** completed call summaries, formatted as dated lines:

```
Llamada del 15/04/2025: "El lead mostró interés en seguro de auto..."
Llamada del 22/04/2025: "El lead pidió llamar el martes con su esposa."
Llamada del 30/04/2025: "El lead confirmó interés y solicitó cotización."
```

- Dates are displayed in `America/Argentina/Buenos_Aires` timezone (see AD-3).
- Sessions without a summary are **excluded** from call history but still count for `is_returning_caller`.

---

### 2. Confirmed Facts (`{{confirmed_facts}}`)

Assembled from three sources in this order:

#### A. Scalar facts from `Lead.extracted_facts`

**Tier 1** — Known keys, fixed order, Spanish labels (controlled by `_KNOWN_FACTS` list, not dict iteration order — see AD-6):
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

> Nested axis dicts are flattened to one-line summaries. `None`, empty strings, and empty lists are skipped.
> Keys `profile_facts` and `misc_notes` are always skipped here — they have their own dedicated sections below.

#### B. Operational Notes (`--- Notas operativas ---`)

The `misc_notes` dimension produces a sliding-window set of operational notes:

```
--- Notas operativas ---
- [pending_topic] El lead quería comparar precios antes de decidir
- [temporary_context] Espera a su esposa para el martes
- [caution] Irritable si se lo interrumpe
```

- Up to 5 notes, max 3 preferred.
- Written in `analysis_language`.
- Resolved/expired topics are dropped by the pipeline on each call.

#### C. Accumulated Profile (`--- Perfil acumulado ---`)

Profile facts and interest history from relational tables:

```
--- Perfil acumulado ---
- Estilo de decisión: consulta con su esposa antes de tomar decisiones
- Disponibilidad: disponible solo los martes después de las 18hs
- Preferencia de contacto: prefiere WhatsApp sobre llamadas
- Señales de compra: preguntó por la prima mensual del plan Premium
- Evolución de interés: 30→55→72
```

Token budget: max 10 items per namespace. Namespaces rendered:

| Namespace prefix | Label |
|-----------------|-------|
| `profile:` | Datos personales (grouped by category) |
| `pain:` | Puntos de dolor |
| `service_issue:` | Problemas de servicio |
| `signal:` | Señales de compromiso |
| `buying_signal:` | Señales de compra |

Interest history shows the last 5 data points in chronological order (oldest → newest).

---

## Memory Growth Over Multiple Calls

| After call N | What gets added to memory |
|-------------|--------------------------|
| Call summary generated | Added to `CallSession.summary`; appears in `call_history` on call N+1 |
| Interest level computed | `Lead.interest_level` updated; `LeadInterestHistory` row appended |
| Profile facts extracted | `LeadProfileFact` rows added / updated / superseded |
| Misc notes updated | `Lead.extracted_facts["misc_notes"]` replaced with sliding window |
| Data corrections applied | `Lead` columns updated; `LeadProfileFact` rows added for audit |
| `next_action` decided | `Lead.next_action`, `Lead.next_action_at` updated |

After 5+ calls, `build_memory_context()` returns:
- Up to 3 call summaries (most recent)
- Full accumulated interest history (up to 5 data points)
- All active profile facts (grouped by category)
- Current operational notes (3–5 notes, freshly updated)

---

## Per-Session Cache

`build_memory_context()` is called **once per incoming webhook request** (not once per turn). The generated system prompt is stored in the in-memory `ConversationState` and reused for all subsequent turns in that call.

Session state is managed by `app/voice/session.py` (`session_store`). Sessions expire after **5 minutes of inactivity** (TTL cleanup background task runs every 60 seconds).

---

## Architecture Decisions

| ID | Decision |
|----|---------|
| AD-1 | `build_memory_context` lives at `app/memory.py` (top-level) — serves both the Custom LLM path (`prompts/loader.py`) and the Twilio/SIP path (`voice/initiation.py`) without circular imports |
| AD-2 | `MemoryContext` is a `TypedDict` so it merges into the variables dict via `{**vars, **memory}` |
| AD-3 | Dates are converted to `America/Argentina/Buenos_Aires` timezone before formatting (hardcoded; could be per-client in the future) |
| AD-6 | `confirmed_facts` Tier 1 key ordering is fixed by the `_KNOWN_FACTS` list in code, not by dict iteration order |
