# 21 — Revisión temporal y ajustes a la auditoría de code-state

> **Propósito.** Este documento explica cómo la **vista temporal** (Engram + PRs + roadmap, consolidada en `20-historia-y-evolucion.md`) **revisa** la auditoría de *code-state* (docs `00`–`18`). No reescribe la auditoría: la **contextualiza**. Cada ajuste mantiene el hecho de código verbatim y solo le agrega fecha, intención y *framing*.
>
> **Disciplina de datación.** Todo hito, hallazgo o reencuadre lleva su fecha (`YYYY-MM-DD`) y su fuente (PR#, hash de commit, ID de Engram o sección de `docs/ROADMAP.md`). Cuando una decisión posterior supersede a una anterior, se citan **ambas fechas**.

---

## Tabla de contenidos

1. [Principio rector: los hechos de código NO cambian](#1-principio-rector-los-hechos-de-código-no-cambian)
2. [Qué CONFIRMÓ la historia (el audit acertó)](#2-qué-confirmó-la-historia-el-audit-acertó)
3. [Qué se REENCUADRÓ (cambia el framing, se conserva el hecho)](#3-qué-se-reencuadró-cambia-el-framing-se-conserva-el-hecho)
4. [Qué quedó IGUAL / sigue abierto de verdad](#4-qué-quedó-igual--sigue-abierto-de-verdad)
5. [Posibles correcciones de hecho (revisión humana)](#5-posibles-correcciones-de-hecho-revisión-humana)
6. [Nota sobre la cobertura de Engram](#6-nota-sobre-la-cobertura-de-engram)

---

## 1. Principio rector: los hechos de código NO cambian

Esta revisión opera bajo una **regla de inmutabilidad de code-state**:

- **Lo que Qora literalmente hace hoy y ya tiene programado** (docs `00`–`18`) proviene del código actual y **no se altera**. Si el audit dice que `scheduler/service.py:505` solo marca `in_progress` y no marca, eso queda **verbatim**.
- Esta capa temporal **solo puede AGREGAR** dos cosas: (a) **contexto temporal/intención** (cuándo se decidió algo, por qué, qué lo supersede) y (b) **suavización del *framing* de riesgo** cuando algo está apagado/abierto **por diseño** y no por defecto.
- El **hecho subyacente permanece**. "Durabilidad apagada por flag" sigue siendo cierto; lo que cambia es leerlo como *gated rollout* en vez de *defecto latente*.
- Si la historia revelara que un hecho de code-state del audit es **realmente erróneo**, **no se edita en silencio**: se registra en la [§5](#5-posibles-correcciones-de-hecho-revisión-humana) para revisión humana.

En resumen: **el "qué hace el código" es intocable; el "qué significa eso en el tiempo" es lo que este documento aporta.**

---

## 2. Qué CONFIRMÓ la historia (el audit acertó)

La reconstrucción temporal **valida** varios hallazgos centrales del audit. No solo eran correctos a nivel código: además se explican como decisiones deliberadas y fechadas.

| Hallazgo del audit | Confirmación temporal | Fecha / Fuente |
|---|---|---|
| **El scheduler NO marca llamadas** (solo encola). `scheduler/models.py:43` "Twilio dialing is Phase 8"; `service.py:505` solo marca `in_progress`. | **Confirmado.** El scheduler es *queue-only* desde su nacimiento. El propio `ROADMAP.md` lo afirma: "Scheduler queue (creates scheduled calls, does not dial)" y "No real phone calls yet". El comentario "Phase 8" mapea a **Phase C** del roadmap (no iniciada). | Código 2026-06; diseño original PR #26 (`1c3bb06`, 2026-04-23); ROADMAP 2026-06-10/23 |
| **No hay dialer / nadie marca**. | **Confirmado y explicado**: nadie marca *todavía*, **por diseño**. Las C1–C8 (telephony path, dialer worker, máquina de estados de dialing) están **todas `[ ]`**, explícitamente "after B deployed". | ROADMAP Phase C |
| **Existe un patrón de durabilidad de jobs** (tabla `background_jobs`, `JobExecutor`, retry, dead-lettering). | **Confirmado**: B10 aterrizó como 4 PRs apilados que reemplazan el `asyncio.create_task` fire-and-forget por jobs durables respaldados por DB. | PR #119–#122 (2026-06-25); Engram #2139 |
| **La finalización de transcript corre fuera de la llamada** (off-call). | **Confirmado y reforzado como regla de producto**: la latencia en vivo es restricción innegociable; los jobs durables per-turn están **prohibidos** durante el streaming. | PR #122 (`b3dd320`, 2026-06-25); Engram #2142 |
| **Único adapter CRM real = Airtable** (pese a estructura per-provider). | **Confirmado**: la arquitectura per-provider (2026-05-29) sugiere multi-CRM, pero solo Airtable está implementado; "multi-CRM simultáneo" es out-of-scope. | Commits `dfefed0`/`8b4051b` (2026-05-29); ROADMAP |
| **Columnas Quintana (`car_make`, `car_model`, `age`, …) siguen en el esquema.** | **Confirmado**: están deprecadas **en sitio** (no dropeadas) desde 2026-06-08; el `DROP COLUMN` se difirió. El esquema actual aún las contiene. | Commit `0c3bcf8` (2026-06-08) |
| **Auth implementada pero webhook auth apagada por defecto.** | **Confirmado**: capability ≠ enforcement. `QORA_WEBHOOK_AUTH_ENABLED=false` por defecto para no romper agentes ElevenLabs existentes. | PR #111 (`61c8918`, 2026-06-23) |

**Lectura:** la auditoría de code-state fue **precisa**. La historia no la desmiente; le pone fechas e intención. Donde el audit vio un "hueco", la historia muestra mayormente un **hueco planificado y secuenciado**, no un descuido.

---

## 3. Qué se REENCUADRÓ (cambia el framing, se conserva el hecho)

Cada fila **mantiene el hecho de código del audit** y le añade contexto temporal. El *framing* de riesgo se suaviza **solo** cuando el estado es deliberado y fechado. **Ninguna fila edita el hecho subyacente.**

| Doc(s) | Hallazgo original (hecho de código — se conserva) | Contexto temporal agregado (reencuadre) | Fecha / Fuente |
|---|---|---|---|
| `10`, `17`, `18` | **El scheduler crea llamadas pero no marca**; "pregunta abierta: ¿quién marca?". | El hecho es correcto. La **pregunta abierta queda RESPONDIDA por el roadmap**: es **Phase C — Real Outbound Calls**, todos los ítems `[ ]`, explícitamente "after B deployed". El telephony path (Twilio-native / SIP / ElevenLabs Batch API) **aún no fue elegido** (C1). No es un defecto oculto ni una incógnita: es **deuda deliberadamente secuenciada**. | Código 2026-06; PR #26 (2026-04-23); ROADMAP 2026-06-10/23 |
| `10`, `13`, `17` | **`ENABLE_JOB_EXECUTOR=false`**: la durabilidad está apagada → "un crash pierde el análisis post-call". | El hecho (flag en `false`, runtime durable OFF) es correcto. Pero la **durabilidad YA está implementada** (B10, #119–#122, 2026-06-25); el flag-off es un **rollout gateado por diseño**, con un paso de roadmap explícito: "set `ENABLE_JOB_EXECUTOR=true` after merge & deploy". El riesgo real no es "roto", es **recordar activarlo en/antes del deploy (B2)**. | PR #119–#122 (2026-06-25); Engram #2139, #2142 |
| `08`, `11`, `13`, `17` | **Defaults de seguridad abiertos**: webhook auth off, CORS permisivo. | Los defaults abiertos son ciertos. Reencuadre: B5/B6/B7 **construyeron deliberadamente** la auth de API admin, el secreto de webhook **opt-in** y `QORA_ALLOWED_ORIGINS` configurable (reemplaza el allow-all hardcodeado **para producción**). La capacidad de lock-down **existe**; los valores abiertos son **defaults de DEV**. El producto **aún no está deployado** (B2 "do last after security hardening"). Se **conserva el hallazgo** (defaults abiertos) pero se enmarca como **postura pre-deploy con un flip obligatorio antes de B2**. | PR #107/#109/#111 (2026-06-22/23); ROADMAP B2 |
| `11`, `15`, `16`, `17` | **Scripts `migrate_*.py` legacy**: deuda de migración / "necesitan validación". | El hecho (los scripts existen en el repo) es correcto. Reencuadre: están **explícitamente DEPRECATED desde 2026-06-19**, cuando aterrizó la fundación Alembic. Se conservan **por historia**, superados por la baseline Alembic. No es deuda por validar: es **legacy datado y reemplazado**. | PR #103 (commit `177819b` "docs(db): deprecate legacy scripts", 2026-06-19) |
| `13`, `17`, `18` | **Brechas de observabilidad**: sin correlation id, sin handlers globales de excepción, sin monitoring/alerting. | Los huecos son reales a nivel código. Reencuadre: son exactamente el alcance de **B9 — Structured logging + error monitoring**, el ítem **NEXT** del roadmap (`[ ]`). `jobs/queries.py` (#121) ya es *groundwork* de B9. No es un descuido: es **el siguiente ítem planificado**. | ROADMAP B9; Engram #2142; PR #121 (2026-06-25) |
| `08`, `11` (+ `README`) | **Posible contradicción**: prosa que dice "No authentication" / estado de seguridad. | No es contradicción, es **capas temporales (layering)**. La **TABLA de fases** del `ROADMAP.md` es la fuente de verdad vigente (B5/B6/B7 = `[x]`). La **prosa "Current State" → "No authentication"** era cierta el 2026-06-10 pero quedó **STALE tras B5** (auth completada 2026-06-22/23). `README.md:11` también rezaga. **Severidad baja** (desfase de prosa), no un conflicto de hecho. | ROADMAP prosa 2026-06-10 (stale) vs. tabla 2026-06-23/25; README.md:11 |
| `09`, `06`, `10` | **Hallazgos "novedosos"**: drift de tipos TS manuales; turnos agent/user duplicados en el webhook de streaming. | Ambos **ya están trackeados** en el roadmap como known-issues. "Manual TS types drift" = **P4** (generated API types pendiente). "Duplicate agent/user turns en streaming webhook" = **P3**. Cross-referencia: **no son hallazgos nuevos**, son issues conocidos y priorizados. | ROADMAP known-issues P3/P4 (2026-06-10) |

> **Nota de *framing* (suavización autorizada).** En todos los casos anteriores el cambio es de **lectura**, no de **hecho**. "Apagado", "abierto", "no marca" y "legacy presente" **siguen siendo verdad**. Lo que se agrega es que esos estados son **deliberados, fechados y secuenciados**, lo cual baja la alarma sin tocar el dato.

---

## 4. Qué quedó IGUAL / sigue abierto de verdad

La historia **no** convierte todo hueco en "por diseño". Lo siguiente sigue **genuinamente abierto** al cierre de esta revisión (2026-06-25) y se reporta tal cual lo vio el audit, sin suavizar:

- **No hay llamadas reales (outbound ni inbound).** Phase C y Phase D están **todas `[ ]`**. Qora hoy **no marca ni recibe teléfono**. (ROADMAP Phase C/D)
- **No hay deploy público.** B2 `[ ]`; el producto corre local + ngrok. El endpoint HTTPS público para webhooks **no existe aún**. (ROADMAP B2)
- **`ENABLE_JOB_EXECUTOR` sigue en `false`.** La durabilidad existe pero **no está activa** en runtime; queda el riesgo operativo real de **olvidar el flip** al desplegar. (PR #119–#122, 2026-06-25)
- **Webhook auth y CORS abiertos por defecto.** Capability presente, **enforcement ausente** por defecto. Antes de B2 hay un **flip de seguridad obligatorio**. (PR #111, 2026-06-23)
- **Observabilidad de producción sin construir.** Sin logging estructurado ni monitoring (B9 `[ ]`, NEXT). (ROADMAP B9)
- **Postgres no implementado.** B3 deferido **por decisión sostenida** de quedarse en SQLite; abierto, pero **intencionalmente**. (ROADMAP B3)
- **Production Operations (Phase E) sin empezar.** Billing, auditoría de aislamiento tenant, retención, dashboard ops, health checks, playbook de incidentes: **todo `[ ]`**. (ROADMAP Phase E)
- **Known-issues P2–P4 vigentes.** P2 (`leads.status` mezcla CRM vs interno; extracción prose-instead-of-tags; polución dual-write de `lead_profile_facts`; orden de merge de `data_corrections`), P3 (turnos duplicados en streaming, pulido de UI de mapeo, flicker de remount de custom field, endpoint de call history débil) y P4 (tipos TS generados, sync programático de ElevenLabs, runbook de producción) **siguen tracked y abiertos**. (ROADMAP known-issues)

> **Diferencia clave con la §3.** Aquí no hay reencuadre: estos puntos **no se suavizan**. La §3 explica por qué un estado es deliberado; la §4 confirma que el estado **sigue ahí**.

---

## 5. Posibles correcciones de hecho (revisión humana)

> **Regla.** Si la historia sugiere que un **hecho de code-state** del audit (docs `00`–`18`) podría estar **mal**, **no se corrige aquí ni se afirma como arreglado**. Se **lista** para que un humano lo valide contra el código actual. Ninguno de los puntos siguientes debe tomarse como confirmado.

Durante la reconstrucción **no se detectó ningún hecho de code-state del audit directamente contradicho** por la historia. Los puntos siguientes son **señalamientos de posible incompletitud o desfase**, no errores confirmados:

1. **Modelo de datos de leads descrito solo por columnas Quintana.**
   Si algún doc (`07` modelo de datos, u otro) describe `car_make` / `car_model` / `car_year` / `current_insurance` / `age` / `zona` como el **modelo de leads vigente** **sin mencionar `lead_custom_fields` ni `lead_profile_facts`**, el hecho **no es falso** (las columnas siguen en el esquema) pero está **incompleto**: desde 2026-06-08 (`0c3bcf8`) el modelo **canónico** es de **3 niveles** (`leads` + `lead_custom_fields` + `lead_profile_facts`) y esas columnas están **deprecadas en sitio**. → **No editar el hecho de código; verificar y, si aplica, anotar el contexto de 3 niveles.**

2. **Cualquier afirmación de "durabilidad de transcript durante la llamada en vivo".**
   Si en revisión humana se confirma que algún doc afirma que la finalización/durabilidad de transcript corre **per-turn durante la llamada en vivo**, sería un **posible error de hecho**: la regla off-call de **PR #122 (2026-06-25)** lo **prohíbe explícitamente** (la persistencia durable corre antes de iniciar, tras fin normal, o tras corte). → **Verificar contra `transcript_flush.py` / `app/jobs/` antes de afirmar nada.**

3. **Cualquier mención de n8n como componente presente.**
   Si algún doc del audit menciona **n8n** como parte del producto **actual**, sería **stale**: n8n fue descomisionado el 2026-04-29 (`6872f3f`) y sus artefactos **borrados físicamente** en PR #89 (2026-05-15/17). **Nunca quedó en el producto final.** → **Verificar que no haya referencias residuales que el audit haya leído como vigentes.**

4. **Cualquier afirmación de "migraciones DDL en el startup" como mecanismo vigente.**
   Si un doc describe `ALTER TABLE` idempotentes en el arranque (`_ensure_startup_schema_compat`, `create_all()`) como el **mecanismo actual** de migración, sería **estado anterior al 2026-06-19**: Alembic (PR #103, `d483023`) **superseded** ese patrón. → **Verificar contra `alembic/` + `backend/scripts/migrate.py`.**

5. **Cualquier descripción de "prompt del agente en DB" como fuente de verdad.**
   Si algún doc presenta `Agent.system_prompt` (DB) como la **fuente de verdad** del prompt, sería **estado anterior al 2026-05-11**: PR #75 **revirtió** la fuente de verdad a **filesystem** (`clients/{id}/agents/{slug}/system-prompt.md`); la DB quedó como **fallback legacy**. → **Verificar contra `PromptLoader` antes de afirmar.**

6. **`ENABLE_JOB_EXECUTOR` "no documentado en ningún lado" — VERIFICADO Y CORREGIDO (2026-06-27).**
   El doc `11` (§9 tabla de divergencias, fila 1; y la tabla de §"Variables de entorno") afirmaba que el flag está *"ausente de `.env.example` **y de toda la doc de setup**"* / *"invisible para el operador"*. **Verificado por inspección read-only del repo:** la mitad **`.env.example` es CORRECTA** (el flag efectivamente no aparece ahí), pero la mitad **"toda la doc de setup" es FALSA** — `docs/ops/background-jobs.md` documenta el flag (tabla de config + comportamiento `true`/`false` + rollback, líneas 15/20/150), escrito junto con B10 (`d9afe17`, 2026-06-25). A diferencia de los puntos 1–5, **este sí se corrigió** en `11-configuracion-env-deployment.md` mediante una nota de corrección datada, por contar con **evidencia directa**. Fuente: `docs/ops/background-jobs.md:15,20,150` vs `.env.example`.

> **Importante.** Los **puntos 1–5 son candidatos a revisión** (no correcciones aplicadas). El **punto 6 sí se verificó y corrigió** con evidencia read-only directa. Salvo esa corrección puntual en `11`, este documento **no modifica** los docs `00`–`18`.

---

## 6. Nota sobre la cobertura de Engram

La vista temporal se apoya en dos fuentes muy desiguales en el tiempo, y eso **condiciona cómo leer esta revisión**:

- **Engram tiene esencialmente CERO memoria persistida antes de ~2026-06-24.** Búsquedas amplias (arquitectura temprana, pipeline de análisis, CRM/Airtable, voz/skills, migraciones, auth/CORS) devuelven todas **"No memories found"**. Engram se adoptó sistemáticamente **recién en la era B10** (fines de junio 2026).
- En consecuencia, **"el proyecto visto a través de Engram" = únicamente el capítulo B10** (2026-06-25) más la disciplina de revisión adversarial que se volvió estándar entonces. La memoria B10 incluye `#2139` [architecture] (cierre de B10), `#2142` [session_summary] (preferencias del usuario + next steps) y ~15 observaciones de revisión.
- **Toda la historia profunda (abril a mediados de junio 2026) vive SOLO en PRs / commits / SDD / OpenSpec / docs**, no en Engram. Por eso esta revisión fecha el período temprano con **hashes de commit y PR#**, no con IDs de memoria.

**Consecuencia para esta revisión:** la ausencia de Engram temprano **no significa "no pasó nada"** — pasó **casi todo el producto**. Es una limitación de la herramienta de memoria, no del registro histórico (que sí existe en `git`). Donde este documento cita Engram (#2139, #2142 y las observaciones de revisión), está citando **exclusivamente** el contexto B10 del 2026-06-25; cualquier reencuadre de la era abril–mediados de junio se sostiene en PRs/commits, no en memoria persistida.

---

*Documento de revisión temporal. Acompaña a `20-historia-y-evolucion.md` y contextualiza —sin modificar— los hechos de code-state de los docs `00`–`18`.*
