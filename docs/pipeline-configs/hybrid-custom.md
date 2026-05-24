# Hybrid Custom pipeline

Hybrid Custom significa que Qora controla transport, mixing, turn-taking y barge-in, pero usa vendors especializados para STT y TTS. Es el primer modo donde Qora puede tener background audio completo, aunque el costo técnico sube fuerte.

## TL;DR

| Tema | Respuesta |
|------|-----------|
| Recomendación | Usar cuando background audio y control de pipeline sean requisitos de producto, no solo nice-to-have. |
| Qora controla | Audio gateway, mixing, turn-taking, barge-in, routing, LLM, tools, memory y CRM. |
| Vendors | STT con Deepgram/AssemblyAI; TTS con ElevenLabs TTS API, Cartesia o Deepgram TTS. |
| Phone | Twilio bidirectional Media Streams con `mulaw/8000`. |
| Web | WebSocket/WebRTC + Web Audio API. |
| Background audio | Control total: server-side para phone, client-side o server-side para web. |
| Costo | Aproximadamente USD 80-420/mes según vendors y volumen. |
| Timeline | 4-10 semanas para MVP. |
| Riesgo principal | Turn detection y barge-in son la parte difícil. |

Docs útiles:

- [Twilio Media Streams](https://www.twilio.com/docs/voice/media-streams)
- [Twilio bidirectional Media Streams](https://www.twilio.com/docs/voice/media-streams#bidirectional-media-streams)
- [Deepgram Streaming STT](https://developers.deepgram.com/docs/streaming)
- [AssemblyAI Streaming Speech-to-Text](https://www.assemblyai.com/docs/speech-to-text/streaming)
- [ElevenLabs Text to Speech API](https://elevenlabs.io/docs/api-reference/text-to-speech)
- [Cartesia docs](https://docs.cartesia.ai/)
- [Web Audio API](https://developer.mozilla.org/en-US/docs/Web/API/Web_Audio_API)
- [WebRTC](https://developer.mozilla.org/en-US/docs/Web/API/WebRTC_API)

## Arquitectura

```text
Web client                         Phone caller
WebSocket/WebRTC                   Twilio Media Streams
Web Audio API                      mulaw/8000
      |                                  |
      v                                  v
Qora audio gateway
  - session state
  - stream routing
  - VAD / turn-taking policy
  - barge-in handling
  - background audio mixing
  - transcoding for phone
      |
      +--> STT provider: Deepgram / AssemblyAI
      |
      +--> Qora LLM brain: tools / memory / CRM
      |
      +--> TTS provider: ElevenLabs / Cartesia / Deepgram TTS
      |
      v
Mixed audio back to web or Twilio
```

## Qué controla Qora

| Área | Control |
|------|---------|
| Audio gateway | Qora abre y mantiene sesiones de audio. |
| Mixing | Qora mezcla voice output, background bed y efectos. |
| Turn-taking | Qora define cuándo el usuario terminó de hablar. |
| Barge-in | Qora corta TTS/background según interrupción del usuario. |
| STT provider | Qora elige Deepgram, AssemblyAI u otro. |
| TTS provider | Qora elige ElevenLabs TTS API, Cartesia, Deepgram TTS u otro. |
| Phone transport | Qora integra Twilio Media Streams. |
| Web transport | Qora implementa WebSocket/WebRTC y Web Audio API. |

Este modo convierte a Qora en producto de audio en tiempo real. Eso da control, pero también responsabilidad operativa.

## Background audio

| Canal | Estrategia recomendada |
|-------|------------------------|
| Web | Client-side mixing con Web Audio API para menor carga server y mejor control UX. |
| Phone | Server-side mixing obligatorio antes de enviar audio a Twilio. |
| Grabación | Definir si se graba voz limpia, mixed audio o ambos. |
| Ducking | Qora debe bajar background cuando habla el agent o el usuario. |
| Loops | Usar assets seamless y normalizados. |

Con Hybrid se puede hacer ambient continuo, por agente, por tenant, por etapa de conversación o por tool state.

## Phone

Twilio bidirectional Media Streams permite recibir y enviar audio en una llamada. Para phone hay constraints importantes:

| Constraint | Implicación |
|------------|-------------|
| `mulaw/8000` | Audio narrowband; no esperes calidad de studio. |
| Latency de red | Cada hop se siente. Evitar vendors innecesarios. |
| Mixing server-side | El browser no participa en phone. |
| Barge-in | Hay que detectar speech entrante mientras el agent está hablando. |

## Web

Para web hay dos caminos:

| Camino | Cuándo usarlo |
|--------|---------------|
| WebSocket + Web Audio API | Más simple para MVP controlado. |
| WebRTC | Mejor para realtime media serio, NAT/network handling y evolución. |

En ambos casos, Qora debe definir el contract de eventos: audio chunks, transcript partials, agent speech start/stop, interruption, background state y errors.

## Latency budget

Target honesto para MVP: 700-1500ms de respuesta percibida. Menos es mejor, pero no prometas sub-500ms sin medir.

| Tramo | Presupuesto orientativo |
|-------|-------------------------|
| Capture + transport | 50-200ms |
| STT partial/final | 150-500ms |
| Turn detection | 100-500ms |
| LLM first token | 150-700ms |
| TTS first audio | 150-600ms |
| Mixing + playback | 20-150ms |

El gran enemigo no es un tramo aislado: es la suma de buffers conservadores.

## Cost model

Estimación para 1000 minutos:

| Componente | Rango |
|------------|-------|
| STT streaming | Variable por provider y modelo. |
| TTS | Variable fuerte; ElevenLabs suele ser más caro que alternativas commodity. |
| Twilio phone | Costo por minuto y número. |
| Infra Qora realtime | CPU/network/concurrency. |
| Total aproximado | USD 80-420/mes. |

La dispersión es real. El costo depende de idioma, voice, concurrency, porcentaje phone/web, duración media y si se graba audio.

## Phased plan

| Fase | Objetivo | Salida |
|------|----------|--------|
| Spike | Probar STT/TTS/mixing con audio real. | Latency y calidad medidas. |
| Web MVP | WebSocket/WebRTC + Web Audio API + ambient. | Demo web usable. |
| Phone MVP | Twilio Media Streams + server-side mixing. | Llamada phone funcional. |
| Production hardening | Observability, retries, scaling, fallbacks. | Sistema operable por tenant. |

## Implementation checklist

- [ ] Definir event protocol del audio gateway.
- [ ] Elegir STT provider inicial.
- [ ] Elegir TTS provider inicial.
- [ ] Implementar streaming STT con partial/final transcripts.
- [ ] Implementar TTS streaming o chunked playback.
- [ ] Implementar background loop y ducking.
- [ ] Implementar barge-in real: cortar TTS al detectar user speech.
- [ ] Implementar WebSocket/WebRTC web client.
- [ ] Implementar Twilio Media Streams para phone.
- [ ] Medir latency end-to-end por tramo.
- [ ] Agregar tracing por conversation/session.
- [ ] Definir fallbacks si STT/TTS/provider falla.

## Riesgos

| Riesgo | Impacto | Mitigación |
|--------|---------|------------|
| Turn detection débil | Conversaciones torpes, interrupciones falsas o silencios largos. | Spike temprano con audio real. |
| Barge-in incorrecto | El agent habla encima o se corta de más. | Diseñar state machine explícita. |
| Transcoding phone | Bugs de audio difíciles de depurar. | Tests con fixtures de audio y llamadas reales. |
| Latency acumulada | UX peor que provider managed. | Presupuestar por tramo y medir continuamente. |
| Operación realtime | Concurrency y network pasan a ser core. | Backpressure, timeouts y observability desde el MVP. |

## Rollback

1. Mantener ElevenLabs ConvAI o VAPI/Retell como modo alternativo por agente.
2. Si el gateway falla, mover el agente afectado al provider managed.
3. Apagar phone Hybrid antes que web si Twilio/mixing degrada.
4. Preservar Qora LLM brain y tools sin migración de dominio.

## Open questions

- ¿Qué canal importa primero: web o phone?
- ¿Qué nivel de barge-in es aceptable para ventas/demo?
- ¿Necesitamos grabar mixed audio o audio limpio por stream?
- ¿Cuál es el latency máximo tolerable antes de que la UX se sienta mala?
- ¿El equipo está listo para operar realtime audio como parte central del producto?
