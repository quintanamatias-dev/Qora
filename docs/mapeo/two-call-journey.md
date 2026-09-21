# Circuito simulado de dos llamadas

[**Abrir el mapa funcional**](recorrido.html). Es una simulación local, ficticia y autocontenida: no llama, no lee registros ni hace requests. El circuito espacial muestra qué información vuelve a la segunda llamada; no promete una venta ni una conversión.

## Lectura rápida

1. Pulsá **Reproducir**: los paquetes neón siguen las flechas del circuito, incluida la vuelta de próxima agenda al scheduler.
2. Hacé click o foco + <kbd>Enter</kbd> sobre un nodo para abrir su inventario exacto sin agrandar el mapa.
3. En la llamada 2, el centro **Memoria del contacto** ya contiene los hechos ficticios persistidos en la llamada 1.

## Flujo y límites

| Tramo | Hecho de código reflejado | Límite de la simulación |
|---|---|---|
| Entrada → registro | Los contactos pueden crearse por la API/UI de leads. También existe importación CRM batch configurada, separada de la llamada en vivo. | No presenta CRM como una ingestión automática durante la llamada. |
| CALL interno | El contexto de voz reúne perfil, campos, notas e historial para contacto/agente; prompt, skills y herramientas son configuraciones del agente. | El ejemplo no ejecuta proveedor, modelo ni llamada. |
| Captura → transcripción | `capture_data` valida propiedades declaradas y escribe campos/facts; no cambia el estado del contacto. | «Mañana después de las 16» y la necesidad de hogar son datos deterministas ficticios. |
| Análisis → savepoint | Seis ejes universales: resumen, objeciones, resultado, problema/necesidad, incidentes de servicio y compromisos. Corren además pipelines de intereses+nivel, perfil, notas operativas y correcciones; después se decide próxima acción. Las actualizaciones se preservan en un savepoint. | Los seis ejes no son campos personalizados por cliente. |
| Persistencia → CRM / agenda | Contacto, llamada, análisis, perfil, notas, historial y la evaluación de auto-agenda quedan en el savepoint. El sync CRM se despacha después y puede ser no-op. | El CRM es un espejo downstream: no causa la agenda ni la segunda llamada. |
| Próxima agenda → llamada 2 | El scheduler existe aunque el marcado automático tenga flags. Para autodial aplican habilitación, elegibilidad, opt-out, agenda activa y límite de intentos. | «Mañana 16:30» es una hora explícitamente elegida para este ejemplo, no un default universal. |

## Inventario del contexto recuperado

La segunda llamada recupera el resumen de la primera, horario y necesidad capturados, perfil, notas y hechos/historial del mismo contacto. El mapa lo llama **Memoria del contacto** para hacerlo visible, pero no representa una base de entrenamiento ni un cerebro independiente.

## Configurable hoy vs. extensión posible

- **Implementado/configurable:** campos y mapeos de `crm.yaml`, configuración de herramientas por agente, idioma de análisis, umbrales de próxima acción, ventanas horarias, intentos y cooldown.
- **No presentado como ejecutado:** dimensiones de análisis específicas por cliente. `extraction_config` no cambia los ejes ni prompts que este recorrido muestra.
- **Accesibilidad:** sin autoplay; Play/Pausa/Reiniciar y ritmo son operables por teclado. Movimiento reducido conserva el dwell de lectura y detiene el viaje de paquetes.

## Evidencia de implementación

- [leads router](../../backend/app/leads/router.py) y [CRM import](../../backend/app/integrations/crm_import_service.py): alta API/UI e importación batch, respectivamente.
- [summarizer.py](../../backend/app/summarizer.py): análisis, savepoint, auto-agenda y despacho CRM posterior.
- [universal dimensions](../../backend/app/analysis/universal/__init__.py) y [schema](../../backend/app/analysis/schema.py): seis dimensiones universales y composición post-llamada.
- [capture_data](../../backend/app/tools/capture_data.py): esquema configurado, captura sin transición de estado.
- [scheduler](../../backend/app/scheduler/service.py), [contexto de voz](../../backend/app/voice/context.py) y [CRM sync](../../backend/app/integrations/crm_sync_service.py): guardas de agenda, contexto por sesión y espejo downstream.

El [workflow nativo de Archify](diagrams/06-two-call-journey.html) sigue siendo un complemento generado. Para redistribuir HTML nativo, conservá [ARCHIFY-NOTICE.md](ARCHIFY-NOTICE.md).
