# Arquitectura local observada

Qora separa una SPA React, una API FastAPI y un runtime de voz. La API central monta routers bajo `/api/v1`; la aplicación web ofrece rutas para leads, detalle de llamadas, analítica y administración.

[Abrir contexto local interactivo](diagrams/01-system-context.html)

## Recorrido principal

| Capa | Implementación observada | Referencia |
|---|---|---|
| UI | React Router; pantallas de leads, calls, analytics y admin. | [router](../../frontend/src/router.tsx), [cliente API](../../frontend/src/api/client.ts) |
| API | `api_v1_router` incorpora clientes, agentes, leads, calls, voz, scheduler, analítica, CRM, demo y outbound. | [main.py#L292-L306](../../backend/app/main.py#L292-L306) |
| Voz | Inicio, contexto, sesión en memoria y Custom LLM SSE. | [voice](../../backend/app/voice/) |
| Datos | Sesiones async ORM; los modelos de scheduler y jobs se registran al inicializar DB. | [database.py](../../backend/app/core/database.py) |
| Autorización | API key, secretos de webhook, firma de ElevenLabs y sesión autorizada. | [auth.py](../../backend/app/core/auth.py) |

## Límites entre sistemas

- **ElevenLabs** llama la iniciación y el Custom LLM; la salida outbound usa su API cuando está habilitada.
- **OpenAI** recibe el streaming del LLM de voz y el análisis posterior. No se verificaron claves, modelos realmente seleccionados ni respuestas remotas.
- **Airtable/CRM** aparece como integración configurable; la documentación no asume que esté configurada ni sincronizada.

## Estado de capacidades

| Estado | Qué significa aquí |
|---|---|
| Implementado en código | Router, servicio o handler presente en el checkout inspeccionado. |
| Feature-gated | El executor y outbound están desactivados por defecto; el scheduler tick, en cambio, se inicia sin condición y sus flags cambian el comportamiento del ciclo. |
| Runtime no verificado | DB, configuración de clientes, secretos, proveedores, workers y llamadas reales. |
| Planeado | No se atribuye comportamiento planeado como si estuviera operativo. |

Los README y documentos antiguos mencionados en el encargo contienen afirmaciones divergentes sobre tools/scheduler; este mapa prioriza código fuente local y documenta los límites, sin modificarlos.
