# Self-hosted pipeline

Self-hosted significa que Qora intenta controlar la mayor parte del voice stack: STT, TTS, VAD, audio gateway, mixing y orchestration. Da máximo control, pero es el camino más lento, caro en baja escala y operativamente más riesgoso.

## TL;DR

| Tema | Respuesta |
|------|-----------|
| Recomendación | Usar solo cuando escala, privacidad, costo unitario o control justifiquen operar modelos propios. |
| Qora controla | Audio gateway, VAD, STT, TTS, mixing, turn-taking, barge-in, LLM, tools, memory y CRM. |
| STT | `faster-whisper` o `whisper.cpp`. |
| TTS | XTTS/Coqui, Fish Speech, Piper u otros modelos. |
| VAD | Silero VAD. |
| Phone | Todavía necesita Twilio u otro carrier. |
| Background audio | Control total. |
| Costo | Alto en bajo volumen: USD 300-2000+/mes; amortiza a escala. |
| Timeline | 2-4+ meses. |
| Riesgo principal | Operación, licensing y gap de calidad contra ElevenLabs. |

Docs útiles:

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- [whisper.cpp](https://github.com/ggerganov/whisper.cpp)
- [Silero VAD](https://github.com/snakers4/silero-vad)
- [Coqui TTS / XTTS](https://github.com/coqui-ai/TTS)
- [Fish Speech](https://github.com/fishaudio/fish-speech)
- [Piper](https://github.com/rhasspy/piper)
- [Twilio Media Streams](https://www.twilio.com/docs/voice/media-streams)

## Arquitectura

```text
Web / Phone
    |
    v
Qora audio gateway
  - WebSocket/WebRTC
  - Twilio Media Streams for phone
  - buffering/transcoding
  - mixing
  - session state
    |
    +--> Silero VAD
    +--> self-hosted STT: faster-whisper / whisper.cpp
    +--> Qora LLM brain: tools / memory / CRM
    +--> self-hosted TTS: XTTS / Fish Speech / Piper
    |
    v
Mixed audio response
```

## Qué se self-hostea

| Componente | Opciones | Comentario |
|------------|----------|------------|
| STT | faster-whisper, whisper.cpp | Whisper es sólido, pero realtime requiere tuning de chunks, VAD y hardware. |
| TTS | XTTS/Coqui, Fish Speech, Piper | Calidad y naturalidad pueden quedar por debajo de ElevenLabs. |
| VAD | Silero VAD | Buen bloque base, igual requiere thresholds y pruebas reales. |
| Mixing | Qora | Full control de background, ducking y efectos. |
| Phone carrier | Twilio | Self-hosted no elimina la necesidad de PSTN/carrier. |

## GPU y scaling

Self-hosted no es gratis: pagás en GPU, complejidad y tiempo de ingeniería.

| Carga | Implicación |
|-------|-------------|
| STT realtime | Necesita GPU o CPU muy optimizada según modelo/concurrency. |
| TTS neural | Normalmente necesita GPU para baja latency y concurrencia. |
| VAD | Liviano; puede correr en CPU. |
| Phone | Transcoding y streaming constante. |
| Scaling | Hay que manejar colas, warm models, autoscaling y fallbacks. |

Patrones necesarios:

- Mantener modelos warm para evitar cold starts.
- Separar workers STT y TTS.
- Limitar concurrency por GPU.
- Medir realtime factor, no solo throughput offline.
- Diseñar fallback a provider hosted si la GPU satura.

## Calidad

No asumir que self-hosted iguala a ElevenLabs. Puede ser suficiente para algunos casos, pero la calidad de voz, prosodia, estabilidad, idioma y emotion control pueden ser peores.

| Área | Riesgo |
|------|--------|
| Naturalidad TTS | Voces menos expresivas o menos consistentes. |
| Latency TTS | Modelos pesados pueden tardar demasiado sin GPU adecuada. |
| STT en ruido | Menor robustez si no se tunea bien. |
| Multilingual | Calidad variable por idioma/modelo. |
| Phone narrowband | `mulaw/8000` degrada input y output. |

## Background audio

Self-hosted da control total:

| Feature | Soporte |
|---------|---------|
| Ambient continuo | Sí |
| Background por agente | Sí |
| Ducking custom | Sí |
| Server-side phone mixing | Sí |
| Client-side web mixing | Sí |
| Efectos/event sounds | Sí |

La pregunta no es si se puede. La pregunta es si vale operar todo lo demás para obtener ese control.

## Cost model

Rango de baja escala: USD 300-2000+/mes.

| Componente | Costo |
|------------|-------|
| GPU instances | Principal driver de costo. |
| CPU/network/storage | Crece con grabaciones y streaming. |
| Twilio | Sigue aplicando para phone. |
| Observability | Necesaria para producción realtime. |
| Ingeniería | Alto costo no visible en hosting. |

A escala, el costo por minuto puede mejorar frente a providers. En bajo volumen, normalmente no.

## Timeline

| Fase | Tiempo orientativo |
|------|--------------------|
| Offline benchmarks | 1-3 semanas |
| Web prototype | 2-4 semanas |
| Phone prototype | 2-4 semanas |
| Production hardening | 4-8+ semanas |
| Total | 2-4+ meses |

## Phased plan

| Fase | Objetivo | Criterio de salida |
|------|----------|--------------------|
| Offline benchmarks | Comparar STT/TTS con datasets reales. | Latency, WER subjetivo y calidad de voz medidos. |
| Web prototype | Probar conversación web realtime. | Barge-in y background funcionando. |
| Phone | Integrar Twilio Media Streams. | Llamada estable con audio aceptable. |
| Production | Operar con métricas, autoscaling y fallbacks. | SLOs mínimos por tenant. |

## Implementation checklist

- [ ] Definir datasets reales de prueba: web, phone, ruido, español.
- [ ] Benchmarkear faster-whisper vs whisper.cpp.
- [ ] Benchmarkear XTTS/Coqui, Fish Speech y Piper contra voces esperadas.
- [ ] Validar licencias de modelos y voces.
- [ ] Implementar Silero VAD con thresholds medidos.
- [ ] Diseñar audio gateway y mixing.
- [ ] Implementar WebSocket/WebRTC web.
- [ ] Implementar Twilio Media Streams para phone.
- [ ] Separar STT/TTS workers y límites de concurrency.
- [ ] Agregar fallback a provider hosted.
- [ ] Medir realtime factor, GPU utilization, latency y errores.

## Riesgos

| Riesgo | Impacto | Mitigación |
|--------|---------|------------|
| Operational complexity | El equipo opera modelos, GPUs y realtime audio. | Empezar con benchmarks y límites claros. |
| Model licensing | Algunos modelos no sirven para uso comercial o clonación. | Revisión legal antes de producción. |
| Quality gap | Puede sonar peor que ElevenLabs. | Comparativas ciegas con usuarios reales. |
| Cost low-volume | GPU idle sale caro. | Usar providers hasta tener volumen. |
| Scaling | Concurrency puede romper latency. | Autoscaling, queues y fallback. |

## Rollback

1. Mantener provider managed por agente como fallback.
2. Si STT o TTS falla, rutear conversaciones nuevas a ElevenLabs ConvAI, VAPI/Retell o Hybrid hosted.
3. No migrar todos los tenants juntos.
4. Guardar configs por agent para volver rápido al modo anterior.

## Open questions

- ¿Qué problema justifica self-hosting: costo, privacidad, control o independencia de vendor?
- ¿Tenemos volumen suficiente para amortizar GPU?
- ¿Qué licencias permiten uso comercial seguro?
- ¿Qué calidad mínima de voz acepta el producto?
- ¿El equipo quiere operar ML realtime como core business?
