# ElevenLabs Agents — Referencia Técnica QORA

Fuente oficial: https://elevenlabs.io/docs/eleven-agents/overview

## WebSocket API (método recomendado para web)

**Endpoint directo:**

```text
wss://api.elevenlabs.io/v1/convai/conversation?agent_id={agent_id}
```

### Flujo de conexión

1. Abrir WebSocket con el `agent_id` o con una signed URL.
2. Enviar `conversation_initiation_client_data` con overrides, dynamic variables y metadata.
3. Recibir/enviar audio en chunks base64.
4. Responder a `ping` con `pong`.

### Mensajes cliente → servidor

```json
// Iniciar conversación con contexto
{
  "type": "conversation_initiation_client_data",
  "dynamic_variables": {
    "lead_name": "Carlos Méndez",
    "car": "Toyota Corolla 2021"
  },
  "custom_llm_extra_body": {
    "lead_id": "lead-quintana-001"
  },
  "user_id": "lead-quintana-001",
  "branch_id": "experiment-branch-a",
  "environment": "production",
  "conversation_config_override": {
    "agent": {
      "prompt": { "prompt": "..." },
      "first_message": "...",
      "language": "es"
    },
    "tts": {
      "voice_id": "pNInz6obpgDQGcFmaJgB"
    },
    "conversation": {
      "text_only": false
    }
  }
}

// Enviar audio del usuario
{
  "user_audio_chunk": "<base64_encoded_pcm_audio>"
}

// Pong (respuesta a ping del servidor)
{
  "type": "pong",
  "event_id": 123
}

// Actualización contextual (no interrumpe)
{
  "type": "contextual_update",
  "text": "El usuario miró la página de precios"
}
```

Campos nuevos relevantes:

| Campo | Uso |
|-------|-----|
| `user_id` | Tracking por usuario/lead. Útil para analytics y continuidad. |
| `branch_id` | Routing explícito para experiments/A-B testing. |
| `environment` | Separar producción/staging. |
| `dynamic_variables` | Variables para prompts, mensajes y tools con sintaxis `{{ var_name }}`. |
| `conversation_config_override.conversation.text_only` | Ejecuta la conversación sin audio cuando aplica. |

### Mensajes servidor → cliente

```json
// Transcripción del usuario
{
  "type": "user_transcript",
  "user_transcription_event": {
    "user_transcript": "Hola, quiero cotizar un seguro"
  }
}

// Respuesta del agente
{
  "type": "agent_response",
  "agent_response_event": {
    "agent_response": "¡Hola! Soy Jaumpablo...",
    "event_id": 1
  }
}

// Audio del agente (PCM base64)
{
  "type": "audio",
  "audio_event": {
    "audio_base_64": "<base64_pcm>",
    "event_id": 1
  }
}

// Ping (responder con pong)
{
  "type": "ping",
  "ping_event": {
    "event_id": 42,
    "ping_ms": 100
  }
}

// Interrupción
{
  "type": "interruption",
  "interruption_event": { "reason": "user_interrupted" }
}
```

Message types adicionales existen para tool calls, vad/turn events y lifecycle events (verificar nombres exactos por versión de API antes de depender de ellos en UI).

## Conversation Flow API

Configuración de turnos confirmada:

```json
{
  "conversation_config": {
    "turn": {
      "turn_timeout": 10,
      "turn_eagerness": "normal",
      "soft_timeout_config": {
        "timeout_seconds": 2.5,
        "message": "Tomate tu tiempo, sigo acá.",
        "use_llm_generated_message": false
      }
    }
  }
}
```

| Campo | Valores / rango | Nota |
|-------|-----------------|------|
| `conversation_config.turn.turn_timeout` | `1` a `30` segundos | Timeout duro de turno. |
| `conversation_config.turn.soft_timeout_config.timeout_seconds` | `0.5` a `8.0` segundos | Default deshabilitado con `-1`. |
| `conversation_config.turn.soft_timeout_config.message` | string | Mensaje fijo para mantener presencia. |
| `conversation_config.turn.soft_timeout_config.use_llm_generated_message` | boolean | Si `true`, el LLM genera el mensaje. |
| `conversation_config.turn.turn_eagerness` | `patient`, `normal`, `eager` | Ajusta cuán rápido responde el agente. |

En Qora, `backend/app/elevenlabs/service.py` ya implementa sync parcial de `soft_timeout_config` con modelos en `backend/app/elevenlabs/models.py`.

## Background Music API

`background_music` está confirmado y funcionando en producción.

```json
{
  "conversation_config": {
    "conversation": {
      "background_music": {
        "source_type": "preset",
        "source_id": "office1",
        "volume": 0.15,
        "crossfade_loop": true
      }
    }
  }
}
```

| Campo | Descripción |
|-------|-------------|
| `source_type` | `preset` o `custom`. |
| `source_id` | Preset o asset custom. Confirmado: `office1`. |
| `volume` | Default `0.6`; Qora usa `0.15` para office ambience. |
| `crossfade_loop` | Evita cortes perceptibles al repetir el loop. |

## Custom LLM

**URL base**: `https://tu-servidor.com`.

ElevenLabs soporta dos contratos:

1. Chat Completions: `POST {base_url}/v1/chat/completions`.
2. Responses API: `POST {base_url}/v1/responses`.

Chat Completions example:

```json
{
  "messages": [...],
  "model": "gpt-4o",
  "temperature": 0.7,
  "max_tokens": 300,
  "stream": true,
  "tools": [...],
  "elevenlabs_extra_body": {
    "lead_id": "lead-001"
  },
  "user_id": "lead-001",
  "branch_id": "experiment-branch-a",
  "environment": "production"
}
```

Cuando system tools están configuradas en ElevenLabs, llegan como OpenAI function calls estándar en `tools`. El Custom LLM de Qora debe devolver tool calls compatibles o ignorarlas de forma explícita si esa tool no está habilitada para el tenant.

### Buffer words (fillers dinámicos)

Enviar primer chunk con `"... "` (ellipsis + espacio) para mantener flujo natural:

```text
data: {"choices": [{"delta": {"content": "Dejame ver eso... "}, "finish_reason": null}]}
```

**Importante**: El espacio después de `...` es crítico para evitar distorsión de audio.

## System Tools

System tools relevantes para Qora:

| Tool | Uso |
|------|-----|
| `end_call` | Terminar conversación con reason y farewell opcional. |
| `language_detection` | Cambiar idioma del agente durante la conversación. |
| `transfer_to_agent` | Handoff a otro AI agent. |
| `transfer_to_number` | Handoff a humano por teléfono. |
| `skip_turn` | El agente queda en silencio hasta que el usuario vuelva a hablar. |
| `voicemail_detection` | Detectar voicemail y ejecutar comportamiento configurado. |

Para Custom LLM, estas tools aparecen en el array `tools` con schema OpenAI-compatible. Qora debe preservar `tool_call_id`/function call semantics cuando responda.

## Workflows API

Workflows permite construir flows conversacionales multi-step desde un builder visual.

Config path:

```json
{
  "conversation_config": {
    "workflow": {
      "nodes": [],
      "edges": []
    }
  }
}
```

Node types documentados:

- `start`
- `end`
- `subagent` / `override_agent`
- dispatch tool
- agent transfer
- transfer to number

Edge types documentados:

- forward
- backward
- unconditional
- LLM-condition
- expression-condition

Subagent nodes pueden overridear system prompt, LLM, voice, knowledge base y tools. Para Qora, esto es útil para separar etapas como qualification, pricing, handoff y closing sin meter todo en un prompt monolítico.

## Knowledge Base API

Fuentes soportadas:

- Files: PDF, TXT, DOCX, HTML, EPUB.
- URLs.
- Texto directo.

Límites no-enterprise: 20MB o 300k caracteres.

SDK/API paths:

```python
client.conversational_ai.knowledge_base.documents.create_from_text(...)
client.conversational_ai.knowledge_base.documents.create_from_url(...)
client.conversational_ai.knowledge_base.documents.create_from_file(...)
```

Agent config path:

```json
{
  "conversation_config": {
    "agent": {
      "prompt": {
        "knowledge_base": [
          { "id": "kb_doc_id" }
        ]
      }
    }
  }
}
```

La forma exacta del item en `knowledge_base` puede incluir más campos según tipo/document version (verificar antes de automatizar PATCH completo).

## Conversation Analysis

Features relevantes:

- Success Evaluation: criterios custom para evaluar calidad, cumplimiento de objetivo o satisfacción.
- Data Collection: extracción estructurada desde transcript, por ejemplo contacto, intención, objection o issue details.
- Smart Search: búsqueda keyword y semántica en historial de conversaciones.

Qora debería consumir estos resultados como analytics auxiliares, no como única fuente de verdad para CRM/memory.

## Experiments / A-B Testing

ElevenLabs soporta experiments branch-based con traffic splits.

Se puede testear:

- Prompt.
- Workflow.
- Voice.
- Tools.
- Knowledge base.
- LLM.
- Evaluation criteria.
- Language.

Notas operativas:

- Routing determinístico por conversation ID.
- Requiere agent versioning habilitado.
- Se puede forzar branch con `branch_id` cuando el flow de Qora necesite control explícito.

## Privacy Controls

Controles documentados:

- Retention settings para transcripts y audio.
- Audio saving toggle.
- Conversation history redaction enterprise: reemplaza datos sensibles con placeholders/bleeps.
- Guidance para GDPR/HIPAA.

Para tenants regulados, definir retention y audio saving antes de activar phone en producción.

## Voice Customization

Updates relevantes:

- Multi-voice para conversaciones multi-character.
- Pronunciation control con IPA/CMU notation en Flash v2.
- Speaking speed `0.7x` a `1.2x`.
- Configuración de voice por idioma.
- Context-aware emotional delivery con Eleven v3 Conversational.

## Personalization / Dynamic Variables

```json
{
  "type": "conversation_initiation_client_data",
  "dynamic_variables": {
    "lead_name": "Carlos Méndez",
    "car": "Toyota Corolla 2021"
  },
  "user_id": "lead-quintana-001",
  "branch_id": "experiment-branch-a",
  "environment": "production"
}
```

Reglas:

- Sintaxis en prompts/messages/tools: `{{ var_name }}`.
- Variables del sistema prefijadas con `system__` no pueden ser sobreescritas por clientes.
- `custom_llm_extra_body` se reenvía al backend como `elevenlabs_extra_body`.
- `user_id` sirve para tracking por usuario.
- `branch_id` sirve para experiments.
- `environment` separa production/staging.
- `text_only` puede enviarse en `conversation_config_override` cuando el canal no debe usar audio.

## SDKs e integraciones

- React SDK.
- Swift SDK para iOS.
- Kotlin SDK para Android.
- React Native SDK.
- ElevenLabs UI component library basada en shadcn.
- SIP trunking.
- Batch outbound calls API.

## CLI

CLI para sincronizar agentes:

```bash
elevenlabs agents pull --agent "<name>"
elevenlabs agents push --agent "<name>"
```

Útil para revisar diffs de configuración y mover cambios entre entornos. Validar siempre secretos/IDs antes de commitear outputs generados por CLI.

## SDK JavaScript

**Problema conocido**: El SDK `@elevenlabs/client` usa WebRTC por defecto vía LiveKit (`livekit.rtc.elevenlabs.io`), que puede fallar en cuentas free/desarrollo.

**Solución**: Usar WebSocket directo (ver arriba) o forzar `connectionType: 'websocket'` en `startSession()`.

**Alternativa recomendada para demo web**: WebSocket nativo del browser.

## Audio

- Formato entrada (usuario → ElevenLabs): PCM 16-bit, 16kHz, mono, base64.
- Formato salida (ElevenLabs → cliente): PCM, base64.
- Chunk size recomendado: ~100ms de audio.
- Background music corre dentro del runtime de ElevenLabs, no lo mezcla el browser de Qora.

## Phone

- Native Twilio integration.
- SIP trunk integration.
- Batch outbound calls API para outbound programático.
- `transfer_to_number` para handoff humano durante llamadas.

## MCP Server Support

ElevenAgents puede conectar agentes a MCP servers para exponer tools y resources. Para Qora, usar esto solo cuando el servidor MCP esté versionado, autenticado y aislado por tenant; si no, preferir tools controladas por el backend.

## Signed URL (para agentes privados)

```bash
GET https://api.elevenlabs.io/v1/convai/conversation/get-signed-url?agent_id={id}
Header: xi-api-key: {key}
```

Devuelve: `{ "signed_url": "wss://api.elevenlabs.io/v1/convai/conversation?agent_id=...&token=..." }`

Usar `signedUrl` en lugar de `agentId` fuerza WebSocket.

## Links oficiales

- [ElevenAgents overview](https://elevenlabs.io/docs/eleven-agents/overview)
- [WebSocket API](https://elevenlabs.io/docs/eleven-agents/api-reference/eleven-agents/websocket)
- [Custom LLM](https://elevenlabs.io/docs/eleven-agents/customization/llm/custom-llm)
- [Widget](https://elevenlabs.io/docs/eleven-agents/customization/widget)
- [Twilio integration](https://elevenlabs.io/docs/eleven-agents/phone-numbers/twilio)

> Última revisión: 2026-05-26
