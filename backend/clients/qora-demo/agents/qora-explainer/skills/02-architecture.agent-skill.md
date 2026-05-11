# QORA — Architecture

## Flujo de una conversación

1. Usuario habla desde el navegador (o futura integración telefónica)
2. ElevenLabs gestiona STT, TTS, voz natural, turn-taking y WebSocket
3. ElevenLabs envía cada turno al backend de QORA via Custom LLM webhook
4. QORA resuelve: cliente → agente → lead → memoria → prompt → herramientas habilitadas
5. QORA construye el system prompt dinámico del agente
6. GPT-4o genera la respuesta
7. QORA ejecuta herramientas si están habilitadas
8. Respuesta vuelve por SSE/streaming a ElevenLabs → voz al usuario
9. QORA persiste transcript, sesión, métricas, memoria y análisis post-call

Resumen no técnico: "ElevenLabs se ocupa de la voz, GPT-4o piensa la respuesta, y QORA conecta todo con el contexto del cliente, el CRM, la memoria y las reglas del agente."

## Modelo Cliente → Agente → Configuración

**Cliente**: empresa, demo u organización aislada dentro de QORA. Tiene su propio CRM, leads, agentes, prompts y configuración. Ejemplos: `quintana-seguros`, `qora-demo`.

**Agente**: entidad conversacional dentro de un cliente. Un cliente puede tener varios agentes. Cada agente tiene prompt, voz, modelo, temperatura, herramientas y configuración propias. Ejemplos: `jaumpablo` (comercial, quintana-seguros), `qora-explainer` (demo, qora-demo).

**Configuración del agente**: system prompt, knowledge base, voz, modelo, temperatura, max tokens, herramientas habilitadas, agente default, activo/inactivo.

**Prompt filesystem**: los prompts canónicos viven en:
`backend/clients/{client_id}/agents/{agent_slug}/system-prompt.md`
Cuando este archivo existe, tiene prioridad sobre el prompt en base de datos.

Separación clave: "Dos empresas usan la misma plataforma sin mezclar contexto, datos ni comportamiento."

## Stack técnico

| Capa | Tecnología |
|------|-----------|
| Backend | FastAPI (Python) |
| Frontend | React + TypeScript + TanStack Query + Vite |
| Voz | ElevenLabs Conversational AI |
| LLM | GPT-4o |
| Base de datos (actual) | SQLite |
| Custom LLM webhook path | `/api/v1/voice/{client_id}/custom-llm/chat/completions` |
| Respuesta al cliente | SSE streaming |
| Telefonía real | Twilio (planificado, no implementado en demo) |

- Clientes y agentes inactivos usan soft delete (no se resuelven como default activo)
- Si un cliente está inactivo, el webhook responde con tenant deshabilitado

## qora-demo

`qora-demo` es el cliente demo de la propia plataforma — no representa una empresa externa.
`qora-explainer` es el agente dentro de ese cliente: Sofia.
Las herramientas están deshabilitadas en este demo (no puede registrar leads, agendar, ni modificar el CRM).
