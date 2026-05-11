# QORA — FAQ

## Preguntas frecuentes

**¿Qué es QORA?**
Plataforma B2B para crear agentes de voz con IA que llaman leads, conversan de forma natural, recuerdan interacciones previas, registran resultados y operan dentro de un CRM/dashboard multi-cliente.

**¿Cómo funciona?**
ElevenLabs maneja la voz, QORA recibe cada turno en su backend, carga el cliente y agente correcto, inyecta contexto y memoria, GPT-4o genera la respuesta, y QORA guarda transcript, sesión y análisis.

**¿QORA es un agente o una plataforma?**
QORA es la plataforma. Los agentes viven dentro de QORA. `qora-demo` es un cliente demo; `qora-explainer` (Sofia) es un agente dentro de ese cliente.

**¿Qué es un cliente?**
Un entorno aislado dentro de QORA con su propio CRM, leads, agentes, prompts, voces y configuración.

**¿Qué es un agente?**
El asistente de IA configurado para un propósito específico dentro de un cliente. Tiene su propio prompt, voz, modelo, herramientas y comportamiento.

**¿Qué hace diferente a QORA de ElevenLabs?**
ElevenLabs da la capa de voz. QORA agrega la capa operativa: multi-tenant routing, CRM, memoria, herramientas, scheduler, análisis post-call, prompts versionables y gestión de agentes.

**¿Puede llamar por teléfono?**
En la demo actual, la conversación funciona vía navegador con ElevenLabs. La telefonía real (Twilio) es una fase futura planificada.

**¿Sirve solo para seguros?**
No. Seguros es el caso piloto principal, pero el modelo —agentes de voz con contexto, memoria, CRM y herramientas— puede adaptarse a otros procesos comerciales o de atención.

**¿Cuánto cuesta?**
No hay tabla de precios en este contexto. La propuesta comercial de QORA es pagar por uso (minutos de conversación) en vez de costos fijos por operadores. Para valores concretos habría que consultarlo con el equipo comercial según volumen, caso de uso e integración.

**¿Dónde se configura este agente?**
El prompt de este agente demo está en `backend/clients/qora-demo/agents/qora-explainer/system-prompt.md`. Ese archivo es la fuente de verdad del comportamiento.

**¿Qué es la demo?**
Una demo mostraría cómo un agente conversa por voz, usa contexto del lead, guarda la transcripción y refleja los resultados en el CRM/dashboard. Para evaluarlo habría que revisar el caso concreto: volumen, tipo de leads, flujo comercial e integraciones necesarias.

## Mapa rápido de conceptos

| Término | Qué es |
|---------|--------|
| QORA | La plataforma |
| qora-demo | Cliente demo de la propia plataforma |
| qora-explainer / Sofia | El agente que sos vos |
| quintana-seguros | Cliente piloto externo |
| Jaumpablo | Agente comercial de seguros en quintana-seguros |
| ElevenLabs | Capa de voz (STT/TTS) |
| GPT-4o | Cerebro conversacional |
| FastAPI | Backend / Custom LLM webhook |
| SQLite | Base de datos actual |
| React | Dashboard y admin |
| Prompt filesystem | Fuente de verdad del prompt del agente |
| DB prompt | Fallback legacy |
| Multi-tenant | Aislamiento por cliente |
| Twilio | Telefonía real planificada (no en demo actual) |
