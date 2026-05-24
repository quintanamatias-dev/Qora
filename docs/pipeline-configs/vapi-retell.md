# VAPI / Retell como pipeline provider

Este modo mantiene a Qora como LLM brain, pero mueve el voice pipeline a VAPI o Retell. Es el camino más corto para tener background audio real con voces ElevenLabs sin construir mixing propio.

## TL;DR

| Tema | Respuesta |
|------|-----------|
| Recomendación | Usar cuando ambient audio en web y phone sea requisito cercano. |
| Qora controla | LLM logic, tenant routing, tools, memory, lead context y CRM. |
| Provider controla | STT, TTS orchestration, VAD, turn detection, barge-in, phone/web transport y background audio. |
| ElevenLabs | Se usa como TTS provider, NO como ElevenLabs ConvAI. |
| Background audio | Sí, built-in en web y phone. |
| Integración Qora | VAPI usa Custom LLM HTTP; Retell usa Custom LLM WebSocket. |
| Costo de referencia | Aproximadamente USD 80-170/mes para 1000 minutos, según STT/TTS/voice. |
| Timeline | Días a 2 semanas para integración inicial. |
| Riesgo principal | Vendor lock-in y margen por minuto. |

Docs útiles:

- [VAPI docs](https://docs.vapi.ai/)
- [VAPI Custom LLM](https://docs.vapi.ai/customization/custom-llm)
- [VAPI assistant configuration](https://docs.vapi.ai/assistants)
- [Retell AI docs](https://docs.retellai.com/)
- [Retell Custom LLM](https://docs.retellai.com/build/custom-llm)
- [ElevenLabs Text to Speech API](https://elevenlabs.io/docs/api-reference/text-to-speech)

## Arquitectura

```text
Web / Phone
    |
    v
VAPI or Retell
  - transport
  - STT
  - VAD / turn detection
  - barge-in
  - background audio
  - TTS orchestration
       |
       | TTS provider
       v
ElevenLabs TTS API / other TTS
       |
       | Custom LLM HTTP or WebSocket
       v
Qora backend
  - tenant routing
  - LLM orchestration
  - tools
  - memory
  - CRM
```

## Decisión clave

VAPI/Retell pueden ofrecer background audio con voces ElevenLabs porque usan ElevenLabs como TTS provider dentro de su propio pipeline. No están usando ElevenLabs Conversational AI como pipeline completo.

Esta diferencia importa:

| Modo | Voice pipeline | ElevenLabs role | Ambient audio |
|------|----------------|-----------------|---------------|
| ElevenLabs ConvAI | ElevenLabs | Pipeline completo | No continuo |
| VAPI/Retell | VAPI/Retell | TTS provider | Sí |

## VAPI

| Área | Detalle |
|------|---------|
| Custom LLM | HTTP endpoint. Qora responde como brain. |
| Background audio | `backgroundSound`, por ejemplo `office` o custom. |
| Hosting/platform cost | Cerca de USD 0.05/min. |
| TTS | Puede usar ElevenLabs como provider. |
| Web | Soportado. |
| Phone | Soportado. |

Configuración conceptual:

```json
{
  "model": {
    "provider": "custom-llm",
    "url": "https://qora.example.com/vapi/custom-llm"
  },
  "voice": {
    "provider": "11labs",
    "voiceId": "..."
  },
  "backgroundSound": "office"
}
```

## Retell

| Área | Detalle |
|------|---------|
| Custom LLM | WebSocket. Qora mantiene sesión conversacional en tiempo real. |
| Background audio | `ambient_sound`, por ejemplo `coffee-shop`, `call-center` u otros presets. |
| Infra cost | Cerca de USD 0.055/min más STT/TTS. |
| TTS | Puede usar ElevenLabs como provider. |
| Web | Soportado. |
| Phone | Soportado. |

Configuración conceptual:

```json
{
  "llm_websocket_url": "wss://qora.example.com/retell/custom-llm",
  "voice_id": "elevenlabs-voice-id",
  "ambient_sound": "coffee-shop"
}
```

## Qué implementa Qora

| Provider | Qora debe implementar | Comentario |
|----------|------------------------|------------|
| VAPI | Custom LLM HTTP endpoint | Más parecido a webhook request/response. |
| Retell | Custom LLM WebSocket | Más estado y lifecycle por sesión. |

Responsabilidades de Qora:

- Resolver tenant y agent desde metadata/provider IDs.
- Cargar lead context y memory.
- Ejecutar tools y CRM actions.
- Generar respuesta LLM con streaming si el provider lo soporta.
- Registrar usage, latency y errores por conversación.
- Mantener una abstracción interna para no acoplar todo el dominio a VAPI o Retell.

## Background audio

Este es el motivo fuerte para elegir este modo.

| Necesidad | VAPI/Retell |
|-----------|-------------|
| Ambient continuo en web | Sí |
| Ambient continuo en phone | Sí |
| Presets tipo office/call-center/coffee-shop | Sí, según provider |
| Custom background sound | Sí en VAPI; validar límites por plan/provider |
| Ducking/mixing avanzado propio | Limitado por provider |

La honestidad técnica: tenés background audio rápido, pero no control fino de DSP/mixing como en Hybrid Custom.

## Costo

Estimación para 1000 minutos:

| Componente | Rango esperado |
|------------|----------------|
| Provider infra | USD 50-55 aprox. |
| TTS | Depende de ElevenLabs u otro provider. |
| STT | Depende del provider/config. |
| Total aproximado | USD 80-170/mes. |

No fijar pricing sin validar proveedor, voice, idioma, concurrency y overage real.

## Timeline

| Fase | Tiempo |
|------|--------|
| Spike con un agent | 1-3 días |
| Endpoint Qora estable | 2-5 días |
| Web + phone demo | 2-5 días |
| Observability y hardening inicial | 3-7 días |
| Total razonable | Días a 2 semanas |

## Riesgos

| Riesgo | Impacto | Mitigación |
|--------|---------|------------|
| Vendor lock-in | Migrar de provider puede requerir reescribir integration layer. | Crear adapter por provider en Qora. |
| Margen por minuto | Infra + STT + TTS puede comerse margen. | Medir usage real y poner límites por tenant. |
| Menos audio control | Background existe, pero mixing avanzado depende del provider. | Aceptar presets o pasar a Hybrid. |
| Debugging difícil | Hay más vendors en la llamada. | Correlation IDs y logs por provider. |
| Diferencias HTTP/WebSocket | VAPI y Retell no tienen el mismo contract. | No diseñar un endpoint único ficticio; usar adapters. |

## Implementation checklist

- [ ] Elegir provider inicial: VAPI o Retell.
- [ ] Crear un agent de prueba con ElevenLabs como TTS provider.
- [ ] Configurar background audio preset.
- [ ] Implementar endpoint HTTP para VAPI o WebSocket para Retell.
- [ ] Mapear provider agent/call IDs a tenant/agente Qora.
- [ ] Validar web y phone.
- [ ] Medir latency, cost per minute y completion rate.
- [ ] Agregar logs con provider name, call ID, tenant ID y agent ID.
- [ ] Documentar fallback y rollback.

## Rollback

1. Desactivar routing de nuevos agentes hacia VAPI/Retell.
2. Volver el agent afectado a ElevenLabs ConvAI.
3. Mantener Qora LLM brain sin cambios de dominio.
4. Revisar logs de provider antes de reintentar.
5. Rehabilitar por tenant, no globalmente.

## Open questions

- ¿El requisito real es ambient audio o control completo de audio?
- ¿Conviene empezar con VAPI por HTTP o Retell por WebSocket?
- ¿Qué provider da mejor soporte para español y phone en nuestro caso?
- ¿Cuál es el margen mínimo aceptable por minuto?
- ¿Necesitamos custom ambient por marca/cliente o alcanzan presets?
