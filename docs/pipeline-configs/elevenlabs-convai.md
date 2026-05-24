# ElevenLabs Conversational AI

Este es el modo que Qora usa hoy: ElevenLabs Conversational AI opera la voz completa y Qora responde como `Custom LLM` por webhook. Es el camino más rápido y estable, pero NO permite ambient audio continuo.

## TL;DR

| Tema | Respuesta |
|------|-----------|
| Recomendación | Usar cuando la prioridad sea salir rápido con web y phone. |
| Qora controla | LLM logic, tools, tenant routing, lead context, memory y CRM. |
| ElevenLabs controla | STT, TTS, turn detection, VAD, barge-in y transport. |
| Background audio | Limitado a `Tool Call Sounds` durante tool execution. No hay ambient continuo. |
| Web | Soportado vía WebSocket, WebRTC, widget y SDK. |
| Phone | Soportado vía integración nativa ElevenLabs + Twilio. |
| Costo de referencia | Pro plan cerca de USD 99/mes con aprox. 1238 minutos incluidos; extra cerca de USD 0.08/min. |
| Riesgo principal | Poco control sobre pipeline de audio y sin ambient bed continuo. |

Docs útiles:

- [ElevenLabs Conversational AI](https://elevenlabs.io/docs/conversational-ai/overview)
- [Custom LLM](https://elevenlabs.io/docs/conversational-ai/customization/llm/custom-llm)
- [Widget](https://elevenlabs.io/docs/conversational-ai/customization/widget)
- [Twilio integration](https://elevenlabs.io/docs/conversational-ai/phone-numbers/twilio)
- [Pricing](https://elevenlabs.io/pricing)

## Arquitectura

```text
Web widget / SDK / WebRTC / Phone
        |
        v
ElevenLabs Conversational AI
  - transport
  - STT
  - VAD / turn detection
  - barge-in
  - TTS
  - phone via Twilio
        |
        | Custom LLM webhook + SSE text response
        v
Qora backend
  - tenant routing
  - lead context
  - LLM orchestration
  - tools
  - memory
  - CRM updates
```

## Qué controla cada parte

| Área | Qora | ElevenLabs |
|------|------|------------|
| STT | No | Sí |
| TTS | No, salvo selección/config del agent | Sí |
| VAD | No | Sí |
| Turn detection | No | Sí |
| Barge-in | No | Sí |
| Transport web | No | Sí |
| Transport phone | No | Sí, con Twilio |
| LLM behavior | Sí | No |
| Tool calls | Sí | Ejecuta la integración conversacional alrededor |
| Tenant routing | Sí | No |
| Lead context / memory / CRM | Sí | No |
| Continuous background audio | No | No en ConvAI estándar |

## Cómo funciona hoy

1. El usuario habla desde web o phone.
2. ElevenLabs recibe audio, detecta turnos, transcribe con STT y decide cuándo llamar al LLM.
3. ElevenLabs invoca el `Custom LLM webhook` de Qora.
4. Qora resuelve tenant, agente, contexto del lead, memoria, tools y CRM.
5. Qora devuelve texto por SSE.
6. ElevenLabs sintetiza la respuesta con TTS y la envía al usuario.

La división es deliberada: Qora es el brain; ElevenLabs es el voice runtime.

## Configuración

| Config | Dueño | Nota |
|--------|-------|------|
| Agent ID | ElevenLabs | Se mapea por cliente/agente en Qora. |
| Voice | ElevenLabs | Configurada en el agent. |
| Custom LLM URL | Qora | Endpoint HTTP que responde streaming text/SSE. |
| Auth del webhook | Qora + ElevenLabs | Usar secret/header por tenant o por agent. |
| Tools | Qora | Qora decide tool use; ElevenLabs solo recibe respuesta final o eventos configurados. |
| Phone number | ElevenLabs/Twilio | ElevenLabs ofrece integración nativa con Twilio. |
| Web widget/SDK | ElevenLabs | Embedding del widget o SDK en la UI. |

Checklist mínimo:

- [ ] Crear agent en ElevenLabs Conversational AI.
- [ ] Configurar voice, language y conversation behavior.
- [ ] Configurar `Custom LLM` apuntando al webhook de Qora.
- [ ] Agregar auth del webhook.
- [ ] Mapear `agent_id` contra tenant/agente interno.
- [ ] Probar web.
- [ ] Probar phone con Twilio si aplica.
- [ ] Medir latency end-to-end con una conversación real.

## Background audio

Este modo NO resuelve ambient audio continuo.

ElevenLabs Conversational AI permite sonidos asociados a tool execution, como typing o elevator music, pero eso aplica mientras una tool está corriendo. No es una pista ambiental persistente detrás de toda la conversación.

| Necesidad | Soporte en ConvAI |
|-----------|-------------------|
| Typing sound durante tool call | Sí |
| Elevator music durante tool call | Sí |
| Coffee shop continuo | No |
| Office ambience continuo | No |
| Control de mix/ducking | No |
| Audio bed distinto por agente | No como feature general del pipeline |

Si el producto necesita ambient audio continuo, este modo no alcanza. Hay que evaluar VAPI/Retell o Hybrid Custom.

## Web y phone

| Canal | Soporte | Comentario |
|-------|---------|------------|
| Web widget | Sí | Camino más simple para demos y sitios. |
| Web SDK | Sí | Más control de UI, mismo pipeline de voz. |
| WebSocket/WebRTC | Sí | Útil para experiencias custom. |
| Phone | Sí | ElevenLabs se integra con Twilio. |

## Costo

Referencia actual para planificación:

| Volumen | Estimación |
|---------|------------|
| Base | Pro plan cerca de USD 99/mes. |
| Minutos incluidos | Aproximadamente 1238 minutos. |
| Overage | Cerca de USD 0.08/min. |

Los precios cambian. Validar siempre contra [ElevenLabs pricing](https://elevenlabs.io/pricing) antes de fijar margen comercial.

## Latency

La latency depende de STT, turn detection, webhook de Qora, LLM, TTS y network. La ventaja es que ElevenLabs optimiza casi toda la cadena de audio. La parte que Qora debe cuidar es el tiempo del `Custom LLM webhook`.

Objetivo operativo:

| Tramo | Objetivo |
|-------|----------|
| Qora webhook first token/text | Lo más bajo posible; evitar tool calls innecesarias. |
| Tool calls | Usar solo cuando aportan valor real. |
| Respuesta total percibida | Medir en conversaciones reales, no solo en logs del backend. |

## Riesgos

| Riesgo | Impacto | Mitigación |
|--------|---------|------------|
| Sin ambient audio continuo | Bloquea experiencias tipo coffee shop/office bed. | Cambiar a VAPI/Retell o Hybrid. |
| Bajo control del audio pipeline | Difícil tunear VAD, barge-in o mixing. | Aceptar constraints o migrar gradualmente. |
| Vendor lock-in | Agent behavior y transport dependen de ElevenLabs. | Mantener Qora como brain y aislar provider config. |
| Costos por minuto | Margen sensible al volumen. | Medir usage por tenant y aplicar pricing con buffer. |
| Debugging distribuido | Fallas pueden estar en Qora o ElevenLabs. | Correlation IDs por conversación. |

## Implementation checklist

- [ ] Confirmar `Custom LLM` contract y formato SSE esperado.
- [ ] Validar auth y tenant routing por agent.
- [ ] Registrar conversation IDs y correlation IDs.
- [ ] Loggear tool calls, latency y errores sin guardar audio sensible innecesario.
- [ ] Definir fallback si Qora no responde.
- [ ] Confirmar web embed o SDK para el canal web.
- [ ] Confirmar Twilio setup para phone.
- [ ] Documentar limitación de background audio para ventas/producto.
- [ ] Medir costo real por tenant.

## Rollback

Rollback recomendado si una configuración nueva falla:

1. Restaurar el agent anterior en ElevenLabs.
2. Revertir el mapping `agent_id -> tenant/agent` en Qora.
3. Desactivar tools nuevas que aumenten latency o errores.
4. Volver a una voice/config estable.
5. Verificar web y phone con una llamada corta.

## Open questions

- ¿El producto necesita ambient audio continuo o alcanza con `Tool Call Sounds`?
- ¿Cada tenant tendrá agent propio en ElevenLabs o se compartirá agent con routing interno?
- ¿Qué SLA de latency vamos a prometer comercialmente?
- ¿Qué datos de conversación se guardan y por cuánto tiempo?
- ¿Qué fallback debe escuchar el usuario si Qora o una tool falla?
