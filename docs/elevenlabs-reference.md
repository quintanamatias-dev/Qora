# ElevenLabs Agents — Referencia Técnica QORA

Fuente oficial: https://elevenlabs.io/docs/eleven-agents/overview

## WebSocket API (método recomendado para web)

**Endpoint directo:**
```
wss://api.elevenlabs.io/v1/convai/conversation?agent_id={agent_id}
```

### Flujo de conexión

1. Abrir WebSocket con el agent_id
2. Enviar `conversation_initiation_client_data` con overrides y extra_body
3. Recibir/enviar audio en chunks base64
4. Responder a `ping` con `pong`

### Mensajes cliente → servidor

```json
// Iniciar conversación con contexto
{
  "type": "conversation_initiation_client_data",
  "custom_llm_extra_body": {
    "client_id": "quintana-seguros",
    "lead_id": "lead-quintana-001"
  },
  "conversation_config_override": {
    "agent": {
      "prompt": { "prompt": "..." },
      "first_message": "...",
      "language": "es"
    },
    "tts": {
      "voice_id": "pNInz6obpgDQGcFmaJgB"
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

## Custom LLM

**URL base**: `https://tu-servidor.com` (ElevenLabs agrega `/v1/chat/completions`)

ElevenLabs llama a `POST {base_url}/v1/chat/completions` con:

```json
{
  "messages": [...],
  "model": "gpt-4o",
  "temperature": 0.7,
  "max_tokens": 300,
  "stream": true,
  "tools": [...],
  "elevenlabs_extra_body": {
    "client_id": "quintana-seguros",
    "lead_id": "lead-001"
  }
}
```

### Buffer words (fillers dinámicos)

Enviar primer chunk con `"... "` (ellipsis + espacio) para mantener flujo natural:

```json
data: {"choices": [{"delta": {"content": "Dejame ver eso... "}, "finish_reason": null}]}
```

**Importante**: El espacio después de `...` es crítico para evitar distorsión de audio.

## SDK JavaScript

**Problema conocido**: El SDK `@elevenlabs/client` usa WebRTC por defecto vía LiveKit (`livekit.rtc.elevenlabs.io`), que falla en cuentas free/desarrollo.

**Solución**: Usar WebSocket directo (ver arriba) o forzar `connectionType: 'websocket'` en `startSession()`.

**Alternativa recomendada para demo web**: WebSocket nativo del browser.

## Audio

- Formato entrada (usuario → ElevenLabs): PCM 16-bit, 16kHz, mono, base64
- Formato salida (ElevenLabs → cliente): PCM, base64
- Chunk size recomendado: ~100ms de audio

## Personalization / Dynamic Variables

```json
{
  "type": "conversation_initiation_client_data",
  "dynamic_variables": {
    "lead_name": "Carlos Méndez",
    "car": "Toyota Corolla 2021"
  }
}
```

## Signed URL (para agentes privados)

```bash
GET https://api.elevenlabs.io/v1/convai/conversation/get-signed-url?agent_id={id}
Header: xi-api-key: {key}
```

Devuelve: `{ "signed_url": "wss://api.elevenlabs.io/v1/convai/conversation?agent_id=...&token=..." }`

Usar `signedUrl` en lugar de `agentId` fuerza WebSocket.
