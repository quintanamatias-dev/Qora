# QORA — Capacidades actuales

## Lo que QORA tiene hoy

| Área | Capacidades |
|------|------------|
| Voz | Conversación vía navegador, ElevenLabs STT/TTS, streaming |
| IA | GPT-4o, Custom LLM webhook (FastAPI), context injection |
| Multi-tenant | Routing por cliente, agentes aislados por empresa |
| Lead context | Inyección dinámica de perfil y datos del lead |
| Memoria | Persistente entre llamadas (resúmenes, hechos, estado) |
| Sesiones | Persistencia, transcripciones turno por turno, métricas base |
| Análisis | Post-call: extracción de hechos, resúmenes, análisis |
| CRM | Leads, historial de llamadas, visor de transcripciones |
| Agentes | Multi-agente por cliente, herramientas configurables |
| Scheduler | Llamadas programadas con lógica de reintentos |
| Prompts | Sistema por filesystem, versionables, prioridad sobre DB |
| Frontend | Dashboard de cliente + panel interno de administración |

## Herramientas de agentes comerciales

Agentes como Jaumpablo pueden tener habilitadas:

- `get_lead_details` — obtener datos del lead
- `register_interest` — registrar que el lead está interesado
- `mark_not_interested` — marcar rechazo
- `schedule_followup` — agendar seguimiento
- Herramientas adicionales de perfil, historial o pain points según configuración

Sofia, en qora-demo, no tiene estas herramientas activas. Puede explicarlas conceptualmente.

## Memoria entre llamadas

QORA puede recordar: resúmenes de llamadas previas, hechos confirmados por el lead, correcciones, estado de la conversación, señales de interés, objeciones y próximas acciones.

"QORA no trata cada llamada como si fuera la primera. Puede recordar qué se habló antes y usarlo para continuar de forma más natural."

Diseño multi-tenant: la información está separada por cliente para evitar mezclar datos entre empresas o agentes.

## Qué no está disponible aún

- Telefonía real (Twilio): planificado para fase futura
- Integraciones externas de CRM (HubSpot, Salesforce, etc.): no confirmadas
- Canales como WhatsApp, Make, Zapier, n8n: no confirmados

Si preguntan por estas integraciones: "No tengo confirmación de que esté implementada hoy. Conceptualmente QORA está diseñada para conectar agentes con datos y herramientas, así que podría evaluarse, pero no debo presentarla como disponible si no está confirmada."
