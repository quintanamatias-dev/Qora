# Mapeo local de Qora

Documentación de una copia local de Qora, basada en `HEAD` `7a3b9fa42ee6ebcf51ad7e402cfa492466dc147f` y lectura de código. Los cambios locales sin commit pueden alterar este retrato; no se ejecutaron servicios, llamadas ni integraciones.

## Inicio rápido

1. **Abrí primero el [mapa espacial de dos llamadas](recorrido.html)**: una simulación local y genérica del circuito de información, con controles de reproducción, ramas paralelas y memoria persistente del contacto.
2. Leé la [guía del recorrido](two-call-journey.md) para distinguir hechos de código, configuración y límites.
3. Leé [arquitectura](architecture.md) para ubicar frontend, API, voz y persistencia.
4. Seguí [voz y herramientas](voice-and-tools.md) para un turno Custom LLM.
5. Consultá [post-llamada y operación](post-call-and-operations.md) para jobs, scheduler y outbound.
6. Revisá [evidencia y límites](evidence-and-limits.md) antes de usar esto como evidencia operativa.

## Diagramas interactivos

Abrí los HTML locales en un navegador moderno; no necesitan servidor ni acceso a Qora:

- [01 · Contexto](diagrams/01-system-context.html)
- [02 · Turno de voz](diagrams/02-voice-turn.html)
- [03 · Herramientas](diagrams/03-tool-execution.html)
- [04 · Post-llamada](diagrams/04-post-call-dataflow.html)
- [05 · Control outbound](diagrams/05-outbound-control-flow.html)
- [06 · Recorrido de dos llamadas (workflow nativo)](diagrams/06-two-call-journey.html) — complemento generado; el mapa espacial interactivo hecho a medida está en [recorrido.html](recorrido.html).

El visor ofrece zoom, búsqueda, foco y temas. La narrativa detallada permanece en Markdown para mantener los nodos legibles; si necesitás más detalle, usá zoom. La interfaz fija del visor queda en inglés porque Archify no soporta `meta.locale` para español.

## Regeneración reproducible

```bash
bash docs/mapeo/regenerate-archify.sh /ruta/a/archify
```

El argumento debe contener `bin/archify.mjs`. El script valida y entrega los seis HTML. Los recibos nativos de `visual-check` se comprobaron contra los hashes de sus HTML y se excluyeron de distribución por contener metadatos de máquina; el resumen sanitizado conserva la evidencia automatizada previa. Ejecutá `visual-check` localmente para reproducir esa evidencia.

## Procedencia y redistribución

Los HTML son artefactos generados por Archify v2.17. Como embeben código sustancial del visor, toda redistribución debe conservar el aviso MIT completo, la atribución de Cocoon AI y los avisos ya embebidos, incluido JetBrains OFL: [ARCHIFY-NOTICE.md](ARCHIFY-NOTICE.md).
