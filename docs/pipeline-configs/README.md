# Pipeline configs de Qora

Estos documentos comparan los modos posibles para operar voice agents en Qora. La decisión central es cuánto controla Qora del pipeline de audio versus cuánto delega a un provider.

## Respuesta corta

La progresión recomendada es:

1. ElevenLabs ConvAI para velocidad y estabilidad hoy.
2. VAPI/Retell si background audio continuo se vuelve requisito cercano.
3. Hybrid Custom si Qora necesita control real de transport, mixing y barge-in.
4. Self-hosted solo cuando escala, privacidad o independencia de vendors justifiquen la complejidad.

Los modos pueden coexistir por agente vía config. No hace falta migrar todo Qora de una vez.

## Qué es un pipeline config

Un `pipeline config` define quién opera cada parte de la conversación de voz:

| Área | Pregunta |
|------|----------|
| STT | ¿Quién convierte audio del usuario a texto? |
| TTS | ¿Quién convierte texto del agent a voz? |
| VAD | ¿Quién detecta si el usuario está hablando? |
| Turn detection | ¿Quién decide que terminó el turno? |
| Barge-in | ¿Quién corta al agent si el usuario interrumpe? |
| Transport | ¿Quién maneja web, phone, WebSocket, WebRTC o Twilio? |
| Mixing | ¿Quién mezcla background audio, ducking y efectos? |
| Brain | ¿Quién decide qué responder, qué tool usar y qué guardar? |

En todos los modos, Qora debería seguir siendo el brain: tenant routing, LLM logic, tools, lead context, memory y CRM.

## Decision matrix

| Modo | Background audio | Web | Phone | Costo aprox. | Timeline | Control | Riesgo principal |
|------|------------------|-----|-------|--------------|----------|---------|------------------|
| [ElevenLabs ConvAI](./elevenlabs-convai.md) | Limitado a tool sounds; no ambient continuo | Sí: widget/SDK/WebSocket/WebRTC | Sí: Twilio nativo vía ElevenLabs | USD 99/mes aprox. con minutos incluidos; overage cerca de USD 0.08/min | Días | Bajo/medio | Sin control fino de pipeline ni ambient continuo |
| [VAPI/Retell](./vapi-retell.md) | Sí, built-in | Sí | Sí | USD 80-170/mes para 1000 min aprox. | Días a 2 semanas | Medio | Vendor lock-in y margen por minuto |
| [Hybrid Custom](./hybrid-custom.md) | Sí, full control | Sí: WebSocket/WebRTC + Web Audio API | Sí: Twilio Media Streams | USD 80-420/mes aprox. | 4-10 semanas | Alto | Turn detection y barge-in |
| [Self-hosted](./self-hosted.md) | Sí, full control | Sí | Sí, pero requiere Twilio/carrier | USD 300-2000+/mes en bajo volumen | 2-4+ meses | Máximo | Operación, licensing y quality gap |

## Cuándo elegir cada modo

### Elegir ElevenLabs ConvAI

Elegilo cuando necesitás vender, demoear o validar rápido con buena calidad de voz y phone/web funcionando.

Es la mejor opción si:

- Ambient audio continuo NO es requisito.
- La prioridad es estabilidad y velocidad.
- Qora necesita concentrarse en LLM, tools, memory y CRM.
- El equipo no quiere operar realtime audio todavía.

No lo elijas si el producto promete coffee shop, office ambience o control fino de mixing durante toda la llamada.

### Elegir VAPI/Retell

Elegilo cuando background audio continuo sea requisito, pero todavía no quieras construir el audio gateway propio.

Es la mejor opción si:

- Necesitás ambient audio en web y phone rápido.
- Querés seguir usando voces ElevenLabs como TTS provider.
- Aceptás pagar margen extra por minuto.
- Aceptás constraints del provider en mixing y transport.

No lo elijas si Qora necesita control DSP fino o independencia fuerte de vendors.

### Elegir Hybrid Custom

Elegilo cuando la experiencia de audio sea parte central del producto y Qora necesite controlar transport, background, barge-in y turn-taking.

Es la mejor opción si:

- Background audio tiene que ser configurable por agente/tenant.
- Phone y web necesitan comportamiento consistente.
- Qora puede invertir 4-10 semanas en MVP.
- El equipo acepta operar realtime audio como infraestructura propia.

No lo elijas para una demo rápida. Es construcción de plataforma, no configuración.

### Elegir Self-hosted

Elegilo solo cuando haya una razón fuerte: escala, privacidad, independencia de vendors, investigación propia o restricciones comerciales que justifiquen operar modelos.

Es la mejor opción si:

- Hay volumen suficiente para amortizar GPU.
- Se validaron licencias de modelos.
- La calidad self-hosted alcanza el estándar del producto.
- El equipo puede operar ML realtime en producción.

No lo elijas solo para bajar costos antes de tener volumen. En baja escala suele ser más caro y más frágil.

## Coexistencia por agente

Qora debería modelar el pipeline como configuración por agente, no como decisión global del sistema.

Ejemplo conceptual:

```yaml
agent_id: demo-cafe
pipeline:
  mode: vapi-retell
  provider: vapi
  background_sound: office
  tts_provider: elevenlabs
```

Esto permite:

- Mantener agentes actuales en ElevenLabs ConvAI.
- Probar VAPI/Retell con un cliente específico.
- Desarrollar Hybrid sin bloquear producción.
- Reservar Self-hosted para experimentos o tenants con necesidades especiales.

## Recomendación de progresión

| Etapa | Objetivo | Señal para avanzar |
|-------|----------|--------------------|
| ElevenLabs ConvAI | Validar producto, web/phone y LLM brain. | Clientes piden ambient continuo o más control. |
| VAPI/Retell | Agregar background audio rápido. | El costo/control del provider empieza a limitar. |
| Hybrid Custom | Controlar experiencia de audio propia. | Hay volumen y necesidad real de plataforma. |
| Self-hosted | Reducir dependencia y optimizar a escala. | Hay capacidad operativa y benchmark superior o suficiente. |

## Principio de diseño

No acoplar el dominio de Qora al provider de voz.

Qora debería tener una capa de `pipeline adapter` por modo/provider, manteniendo estable el core:

- Tenant routing.
- Agent config.
- Prompt/system behavior.
- Tool execution.
- Memory.
- CRM updates.
- Usage tracking.

Así se puede cambiar el pipeline sin reescribir el producto.

## Links rápidos

- [ElevenLabs ConvAI](./elevenlabs-convai.md)
- [VAPI/Retell](./vapi-retell.md)
- [Hybrid Custom](./hybrid-custom.md)
- [Self-hosted](./self-hosted.md)
