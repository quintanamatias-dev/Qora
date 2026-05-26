# ElevenAgents

Este es el modo que Qora usa hoy: ElevenLabs ElevenAgents opera la voz completa y Qora responde como `Custom LLM` por webhook. Es el camino más rápido y estable para web y phone, y hoy sí permite background audio configurado desde el agent.

## TL;DR

| Tema | Respuesta |
|------|-----------|
| Recomendación | Usar cuando la prioridad sea salir rápido con web y phone, manteniendo Qora como brain. |
| Qora controla | LLM logic, tools propios, tenant routing, lead context, memory, CRM y metadata enviada al Custom LLM. |
| ElevenLabs controla | STT, TTS, turn detection, VAD, barge-in, transport, background music, workflows, KB, system tools, experiments y analytics. |
| Background audio | Soportado vía `conversation_config.conversation.background_music`. En producción usamos preset `office1` con volume `0.15`. |
| Web | Soportado vía WebSocket, WebRTC, widget y SDKs. |
| Phone | Soportado vía integración nativa Twilio, SIP trunking y batch outbound calls. |
| Costo de referencia | Pro plan cerca de USD 99/mes con aprox. 1238 minutos incluidos; extra cerca de USD 0.08/min. |
| Riesgo principal | Vendor lock-in y menor control fino del pipeline de audio que en un stack propio. |

Docs útiles:

- [ElevenAgents overview](https://elevenlabs.io/docs/eleven-agents/overview)
- [Custom LLM](https://elevenlabs.io/docs/eleven-agents/customization/llm/custom-llm)
- [Widget](https://elevenlabs.io/docs/eleven-agents/customization/widget)
- [Twilio integration](https://elevenlabs.io/docs/eleven-agents/phone-numbers/twilio)
- [Pricing](https://elevenlabs.io/pricing)

## Arquitectura

```text
Web widget / SDK / WebRTC / Phone
        |
        v
ElevenLabs ElevenAgents
  - transport
  - STT
  - VAD / turn detection
  - barge-in
  - TTS
  - background music
  - workflows / KB / system tools
  - phone via Twilio or SIP
        |
        | Custom LLM webhook + SSE text response
        v
Qora backend
  - tenant routing
  - lead context
  - LLM orchestration
  - Qora-owned tools
  - memory
  - CRM updates
```

## Qué controla cada parte

| Área | Qora | ElevenLabs |
|------|------|------------|
| STT | No | Sí |
| TTS | No, salvo selección/config del agent | Sí |
| VAD | No | Sí |
| Turn detection | No | Sí, con `turn_timeout`, `soft_timeout_config` y `turn_eagerness` |
| Barge-in | No | Sí |
| Transport web | No | Sí |
| Transport phone | No | Sí, con Twilio, SIP y batch outbound calls |
| LLM behavior | Sí, cuando usamos Custom LLM | Ejecuta el runtime y puede enrutar tools/system tools |
| Tool calls | Sí para tools de negocio en Qora | Sí para system tools y tools configuradas en el agent |
| Tenant routing | Sí | No |
| Lead context / memory / CRM | Sí | No, salvo variables/KB configuradas en el agent |
| Background music | Configura/decide por tenant si lo provisionamos | Sí, vía `conversation_config.conversation.background_music` |
| Workflows | Puede diseñar/versionar la lógica de producto | Sí, ejecuta `conversation_config.workflow` |
| Knowledge base | Puede generar/curar contenido | Sí, adjunta documentos al agent prompt |
| Conversation analysis | Consume resultados y persiste analytics | Sí, success evaluation, data collection y smart search |
| Experiments | Decide qué se testea y lee resultados | Sí, branch-based A/B testing con agent versioning |
| Privacy controls | Define política por tenant | Sí, retention, audio saving y redaction enterprise |

## Cómo funciona hoy

1. El usuario habla desde web o phone.
2. ElevenLabs recibe audio, detecta turnos, transcribe con STT y decide cuándo llamar al LLM.
3. ElevenLabs invoca el `Custom LLM webhook` de Qora.
4. Qora resuelve tenant, agente, contexto del lead, memoria, tools y CRM.
5. Qora devuelve texto por SSE.
6. ElevenLabs sintetiza la respuesta con TTS, mezcla background music si está configurado y envía audio al usuario.

La división es deliberada: Qora es el brain; ElevenLabs es el voice runtime.

## Configuración

| Config | Dueño | Nota |
|--------|-------|------|
| Agent ID | ElevenLabs | Se mapea por cliente/agente en Qora. |
| Voice | ElevenLabs | Configurada en el agent; soporta multi-voice, speed y config por idioma. |
| Custom LLM URL | Qora | Endpoint HTTP que responde streaming text/SSE. |
| Custom LLM API | Qora + ElevenLabs | Soporta Chat Completions y Responses API (`/v1/responses`). |
| Auth del webhook | Qora + ElevenLabs | Usar secret/header por tenant o por agent. |
| Tools | Qora + ElevenLabs | Qora maneja tools de negocio; ElevenLabs agrega system tools en `tools`. |
| Workflow | ElevenLabs | `conversation_config.workflow` con `nodes` y `edges`. |
| Knowledge base | ElevenLabs | `conversation_config.agent.prompt.knowledge_base`. |
| Background music | ElevenLabs | `conversation_config.conversation.background_music`. |
| Phone number | ElevenLabs/Twilio/SIP | ElevenLabs ofrece Twilio nativo, SIP trunking y transfers. |
| Web widget/SDK | ElevenLabs | Widget, React SDK, Swift, Kotlin y React Native SDK. |

Checklist mínimo:

- [ ] Crear agent en ElevenLabs ElevenAgents.
- [ ] Configurar voice, language y conversation behavior.
- [ ] Configurar `Custom LLM` apuntando al webhook de Qora.
- [ ] Agregar auth del webhook.
- [ ] Mapear `agent_id` contra tenant/agente interno.
- [ ] Configurar `turn_timeout`, `soft_timeout_config` y `turn_eagerness`.
- [ ] Configurar `background_music` si el agente necesita ambient bed.
- [ ] Configurar system tools necesarias: `end_call`, `transfer_to_agent`, `transfer_to_number`, etc.
- [ ] Probar web.
- [ ] Probar phone con Twilio/SIP si aplica.
- [ ] Medir latency end-to-end con una conversación real.

## Background audio

ElevenAgents sí soporta background music continuo desde la configuración del agent.

Config confirmada:

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

Campos conocidos:

| Campo | Descripción |
|-------|-------------|
| `source_type` | `preset` o `custom`. |
| `source_id` | Identificador del preset o asset custom; ejemplo confirmado: `office1`. |
| `volume` | Volumen del bed. Default documentado: `0.6`; en Qora usamos `0.15` en producción. |
| `crossfade_loop` | Controla loop con crossfade para evitar cortes perceptibles. |

| Necesidad | Soporte en ElevenAgents |
|-----------|------------------------|
| Typing sound durante tool call | Sí |
| Elevator music durante tool call | Sí |
| Coffee shop continuo | Sí, con preset/custom adecuado |
| Office ambience continuo | Sí, confirmado con `office1` |
| Control de mix/ducking | Parcial: `volume`; ducking exacto del pipeline (verificar) |
| Audio bed distinto por agente | Sí, configurando cada agent/branch |

## Conversation flow

Configuraciones confirmadas de turnos:

| Campo | Rango / valores | Nota |
|-------|-----------------|------|
| `conversation_config.turn.turn_timeout` | `1` a `30` segundos | Tiempo máximo de turno antes de actuar. |
| `conversation_config.turn.soft_timeout_config.timeout_seconds` | `0.5` a `8.0` segundos | Default deshabilitado con `-1`. |
| `conversation_config.turn.soft_timeout_config.message` | string | Mensaje cuando el usuario se queda pensando. |
| `conversation_config.turn.soft_timeout_config.use_llm_generated_message` | boolean | Permite que el LLM genere el mensaje. |
| `conversation_config.turn.turn_eagerness` | `patient`, `normal`, `eager` | Controla cuán rápido toma el turno el agente. |

## Workflows

Workflows es una feature mayor para modelar conversaciones multi-step visualmente.

Config path: `conversation_config.workflow` con `nodes` y `edges`.

Node types conocidos:

- `start`
- `end`
- `subagent` / `override_agent`
- dispatch tool
- agent transfer
- transfer to number

Edge types conocidos:

- forward
- backward
- unconditional
- LLM-condition
- expression-condition

Los subagent nodes pueden sobreescribir system prompt, LLM, voice, knowledge base y tools. Para Qora, esto permite separar flows comerciales sin duplicar toda la lógica de tenant/memory en el backend.

## Knowledge base

ElevenAgents permite adjuntar documentos al prompt del agent.

Fuentes soportadas:

- Archivos: PDF, TXT, DOCX, HTML, EPUB.
- URLs.
- Texto directo.

Límites no-enterprise: máximo 20MB o 300k caracteres.

API:

- `conversational_ai.knowledge_base.documents.create_from_text`
- `conversational_ai.knowledge_base.documents.create_from_url`
- `conversational_ai.knowledge_base.documents.create_from_file`

Config path: `conversation_config.agent.prompt.knowledge_base`.

## System tools

System tools importantes para Custom LLM:

| Tool | Uso |
|------|-----|
| `end_call` | Terminar conversación con reason y farewell opcional. |
| `language_detection` | Cambiar idioma del agente durante la conversación. |
| `transfer_to_agent` | Handoff a otro AI agent. |
| `transfer_to_number` | Handoff a humano por teléfono. |
| `skip_turn` | El agente queda en silencio hasta que el usuario vuelva a hablar. |
| `voicemail_detection` | Detectar voicemail y responder según configuración. |

Cuando están configuradas, ElevenLabs las envía como OpenAI function calls estándar dentro del array `tools`. Qora debe tratarlas como parte del contrato del Custom LLM, no como tools de negocio propias.

## Features nuevas relevantes

| Feature | Qué aporta para Qora |
|---------|----------------------|
| MCP servers | Agents pueden conectarse a servidores MCP para tools y resources. |
| Conversation Analysis | Success Evaluation, Data Collection y Smart Search sobre historial. |
| Experiments / A/B testing | Branches con traffic splits; testea prompt, workflow, voice, tools, KB, LLM, evaluation criteria y language. |
| Privacy controls | Retention de transcripts/audio, toggle de audio saving y redaction enterprise. |
| Voice customization | Multi-voice, pronunciation con IPA/CMU en Flash v2, speed `0.7x`-`1.2x`, config por idioma y delivery emocional contextual en Eleven v3 Conversational. |
| Personalization | `{{ var_name }}`, `user_id`, `branch_id`, `environment` y `text_only` override. |
| SDKs | React, Swift, Kotlin y React Native. |
| CLI | `elevenlabs agents pull/push --agent "<name>"`. |
| Phone | Twilio nativo, SIP trunking, batch outbound calls y transfer to number. |

## Web y phone

| Canal | Soporte | Comentario |
|-------|---------|------------|
| Web widget | Sí | Camino más simple para demos y sitios. |
| Web SDK | Sí | Más control de UI, mismo pipeline de voz. |
| WebSocket/WebRTC | Sí | Útil para experiencias custom. |
| Phone Twilio | Sí | Integración nativa. |
| SIP trunk | Sí | Útil para telefonía existente. |
| Batch outbound calls | Sí | Programático para campañas/scheduling. |
| Transfer to number | Sí | Handoff humano durante llamadas. |

## Costo

Referencia actual para planificación:

| Volumen | Estimación |
|---------|------------|
| Base | Pro plan cerca de USD 99/mes. |
| Minutos incluidos | Aproximadamente 1238 minutos. |
| Overage | Cerca de USD 0.08/min. |

Los precios cambian. Validar siempre contra [ElevenLabs pricing](https://elevenlabs.io/pricing) antes de fijar margen comercial.

## Latency

La latency depende de STT, turn detection, webhook de Qora, LLM, TTS, network y features adicionales como tools, KB o workflow branches. La ventaja es que ElevenLabs optimiza casi toda la cadena de audio. La parte que Qora debe cuidar es el tiempo del `Custom LLM webhook`.

Objetivo operativo:

| Tramo | Objetivo |
|-------|----------|
| Qora webhook first token/text | Lo más bajo posible; evitar tool calls innecesarias. |
| Tool calls | Usar solo cuando aportan valor real. |
| Workflow branches | Mantener condiciones simples y observables. |
| Respuesta total percibida | Medir en conversaciones reales, no solo en logs del backend. |

## Riesgos

| Riesgo | Impacto | Mitigación |
|--------|---------|------------|
| Vendor lock-in | Agent behavior, workflow y transport dependen de ElevenLabs. | Mantener Qora como brain y aislar provider config. |
| Bajo control del audio pipeline | Difícil tunear VAD, barge-in o mixing más allá de los knobs expuestos. | Aceptar constraints o migrar gradualmente si el producto exige control extremo. |
| Drift entre dashboard y backend | Configs manuales pueden divergir por tenant/agent. | Provisionar vía API donde exista soporte y auditar cambios. |
| Costos por minuto | Margen sensible al volumen. | Medir usage por tenant y aplicar pricing con buffer. |
| Debugging distribuido | Fallas pueden estar en Qora o ElevenLabs. | Correlation IDs por conversación. |
| Privacy/compliance | Retention o audio saving mal configurados pueden exponer datos. | Política por tenant, retention explícita y redaction enterprise si aplica. |

## Implementation checklist

- [ ] Confirmar `Custom LLM` contract: Chat Completions o Responses API.
- [ ] Validar auth y tenant routing por agent.
- [ ] Registrar conversation IDs, `user_id`, `branch_id`, `environment` y correlation IDs.
- [ ] Loggear tool calls, latency y errores sin guardar audio sensible innecesario.
- [ ] Definir fallback si Qora no responde.
- [ ] Confirmar web embed o SDK para el canal web.
- [ ] Confirmar Twilio/SIP setup para phone.
- [ ] Documentar background music por tenant/agent.
- [ ] Documentar retention/audio saving/redaction por tenant.
- [ ] Medir costo real por tenant.

## Rollback

Rollback recomendado si una configuración nueva falla:

1. Restaurar el agent anterior en ElevenLabs o volver al branch/version estable.
2. Revertir el mapping `agent_id -> tenant/agent` en Qora si cambió.
3. Desactivar workflow branch, tools, KB o experiments nuevos que aumenten latency o errores.
4. Volver a una voice/config estable.
5. Verificar web y phone con una llamada corta.

## Open questions

- ¿Qué configs de ElevenLabs se van a provisionar desde Qora y cuáles quedarán manuales en dashboard?
- ¿Cada tenant tendrá agent propio en ElevenLabs o se compartirá agent con routing interno?
- ¿Qué SLA de latency vamos a prometer comercialmente?
- ¿Qué datos de conversación se guardan, por cuánto tiempo y con qué redaction?
- ¿Qué fallback debe escuchar el usuario si Qora, una tool o un workflow branch falla?
- ¿Qué features requieren agent versioning antes de habilitar experiments?

> Última revisión: 2026-05-26
