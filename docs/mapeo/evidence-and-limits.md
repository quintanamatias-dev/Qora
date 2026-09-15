# Evidencia y límites

## Base del snapshot

| Campo | Valor |
|---|---|
| Checkout documentado | Checkout local (ruta omitida) |
| HEAD observado | `7a3b9fa42ee6ebcf51ad7e402cfa492466dc147f` |
| Caveat | Había cambios locales preexistentes fuera de `docs/mapeo/`; este mapa no los interpreta ni los elimina. |
| Archify | v2.17 según `SKILL.md`; checkout `6db72a9aea3d0f67a6a034e41f8a5491476a11c1` |
| Perfil de diagramas | `showcase`; workflows usan schema v2, los demás schema v1. |

Las afirmaciones se tomaron de los archivos fuente enlazados en esta carpeta. No se leyeron `.env`, bases de datos ni registros privados de clientes. No se ejecutaron Qora, llamadas, webhooks, jobs, CRM ni proveedores externos.

## Evidencia generada

`deliver` informa hashes y bytes de la especificación JSON y del HTML de la misma entrega; comprueba identidad de artefactos, no prueba semántica entre el diagrama y el código. `visual-check` liga su recibo al hash y bytes del **HTML** inspeccionado y recoge contención/capturas de navegador; tampoco es revisión perceptual humana.

Los recibos nativos de `visual-check` se comprobaron contra el hash de sus HTML inspeccionados y se excluyeron de distribución porque contienen rutas y detalles de máquina. [verification-summary.md](verification-summary.md) conserva el resultado automatizado previo en forma sanitizada; es editorial, no un recibo nativo ni evidencia nueva.

Los HTML incorporan código del visor. Conservá el aviso MIT, la atribución Cocoon AI y los avisos embebidos, incluido JetBrains OFL, al redistribuirlos: [ARCHIFY-NOTICE.md](ARCHIFY-NOTICE.md).

## Regenerar y verificar

```bash
bash docs/mapeo/regenerate-archify.sh /ruta/a/archify
```

El script valida y entrega HTML. Ejecutá `visual-check` localmente sólo si necesitás reproducir evidencia de navegador; revisá sus JSON, PNG y contact sheets antes de compartirlos, porque pueden incluir información de entorno.

## Límites de interpretación

- “Implementado” significa presente en el checkout, no desplegado, configurado ni probado contra una dependencia.
- Flags y validadores son evidencia de guardas locales; no prueban valores efectivos de un proceso.
- Los documentos anteriores con enunciados distintos no son la fuente de verdad de este mapa.
- Los diagramas priorizan lectura inicial; usá zoom para inspeccionar etiquetas pequeñas y Markdown para el detalle completo.
