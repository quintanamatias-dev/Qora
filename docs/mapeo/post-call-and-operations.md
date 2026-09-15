# Post-llamada y operaciones

El scheduler arranca como tarea de proceso sin un flag de inicio. Sus flags sólo seleccionan el comportamiento del ciclo; outbound y el executor conservan guardas separadas.

## Después de una llamada

[Abrir diagrama interactivo](diagrams/04-post-call-dataflow.html)

- Con `enable_job_executor=True`, el post-proceso encola handlers durables como `summarize` y `crm_sync`.
- Con `enable_job_executor=False` (default), el resumen y el despacho CRM usan tareas `asyncio.create_task` best-effort; la sincronización CRM no es universalmente un handler de job.
- `scheduler_tick()` se crea sin condición al iniciar la app. En el ciclo, `enable_auto_dialer` + `enable_outbound_calls` habilitan claim/reaper/marcado; la rama flag-off todavía ejecuta `mark_due_calls_in_progress`.
- `auto_schedule` evalúa configuración del cliente, resultado, opt-out, duplicados, intentos y ventana horaria antes de crear un `ScheduledCall`.

Fuentes: [main.py](../../backend/app/main.py), [summarizer.py](../../backend/app/summarizer.py), [jobs](../../backend/app/jobs/), [scheduler/service.py](../../backend/app/scheduler/service.py).

## Llamada saliente

[Abrir diagrama interactivo](diagrams/05-outbound-control-flow.html)

`dial_outbound_call` concentra flag, teléfono E.164, agente configurado, sesiones activas, solapamiento de `ScheduledCall` y persistencia predial. Confirma un `CallSession` `dialing` antes de invocar a ElevenLabs.

> **Brecha observada:** ni el endpoint manual ni `dial_outbound_call` consultan `lead.do_not_call` en las secciones inspeccionadas. El auto-dialer sí lo reconsulta antes de marcar y la iniciación de voz también bloquea ese estado. Este mapa describe la diferencia de código; no infiere explotabilidad ni modifica la aplicación.

| Control | Hecho de código |
|---|---|
| Flags | `enable_outbound_calls=False` y `enable_auto_dialer=False` por defecto. |
| Fail-closed | outbound exige autenticación de webhook; auto-dialer exige outbound activo. |
| Concurrencia | lock por lead, sesión activa y solapamiento de `ScheduledCall`. |
| DNC | Rechequeo en auto-dialer; protección no observada en el disparo manual. |

Fuentes: [outbound/router.py](../../backend/app/outbound/router.py), [outbound/service.py](../../backend/app/outbound/service.py), [scheduler/service.py](../../backend/app/scheduler/service.py), [initiation.py](../../backend/app/voice/initiation.py).
