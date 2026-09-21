# Voz y herramientas

El flujo de voz prepara variables, conserva estado por conversación y transmite la respuesta del LLM como SSE. Un tool call puede interrumpir el primer stream, ejecutar una operación y generar un segundo stream sin tools.

## Turno de voz

[Abrir diagrama interactivo](diagrams/02-voice-turn.html)

1. `POST /voice/initiation` resuelve cliente y, si existe, lead y agente; bloquea leads `do_not_call`.
2. Con `conversation_id`, construye contexto y guarda una `AuthorizedSession` en el store en memoria.
3. El Custom LLM reutiliza el contexto cacheado; si falta, intenta construirlo perezosamente o usa el fallback por turno.
4. Envía prompt, mensajes y definiciones de tools a OpenAI y devuelve SSE compatible.
5. Crea/reutiliza `CallSession` y agenda el guardado del turno del usuario; fallas de persistencia se registran sin cortar necesariamente el stream.

Fuentes: [initiation.py](../../backend/app/voice/initiation.py), [webhook.py](../../backend/app/voice/webhook.py), [session.py](../../backend/app/voice/session.py), [context.py](../../backend/app/voice/context.py).

## Despacho de herramientas

[Abrir diagrama interactivo](diagrams/03-tool-execution.html)

Las definiciones activas se arman desde la configuración del agente y, para `capture_data`, pueden tomar prioridad de `CRMConfig`.

| Condición | Límite observado |
|---|---|
| `authorized_session` presente | Para tools distintas de `load_skill`, el dispatcher valida tenant y los scopes `pipeline:read`/`pipeline:write`. |
| `authorized_session=None` | El dispatcher retorna sin aplicar esa guarda por compatibilidad con callers legacy. |
| `load_skill` | Está exenta del bloque de scope; su ruta especial usa el registry y cache por sesión. |
| Tool retirada | Devuelve `tool_removed`. |

Esto describe una frontera condicional del dispatcher, no una afirmación de explotabilidad. Lecturas activas: `get_lead_details`, `get_lead_profile`, `get_lead_history` y `get_lead_pain_points`; `capture_data` valida contra la configuración disponible.

Al detectar un tool call no cacheado, el webhook puede emitir filler, esperar brevemente, ejecutar y persistir `tool_call`/`tool_result` antes del segundo llamado a OpenAI. Ese segundo stream recibe el resultado como mensaje `tool` y se invoca con `tools=None`.

Fuentes: [registry.py](../../backend/app/tools/registry.py), [dispatcher.py](../../backend/app/tools/dispatcher.py), [capture_data.py](../../backend/app/tools/capture_data.py), [skill_loader.py](../../backend/app/tools/skill_loader.py), [webhook.py](../../backend/app/voice/webhook.py).
