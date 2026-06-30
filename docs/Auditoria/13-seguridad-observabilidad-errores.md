# Área 13 — Seguridad / Observabilidad / Errores

> **Propósito.** Auditoría de solo lectura de la postura de seguridad observable desde el código, el sistema de observabilidad (logging estructurado, health, IDs de correlación) y el manejo de errores (excepciones globales, forma de respuesta, reintentos en jobs/análisis/voz). Se documentan hallazgos con severidad; **no se corrige nada**. Cada afirmación relevante lleva ruta + símbolo y etiqueta de clasificación.

Repo raíz: `/Users/mati/Desktop/Qora`. Backend FastAPI en `backend/app/`.

---

## 1. Resumen ejecutivo

La plataforma tiene una base de seguridad **razonable y deliberada** (Phase B5): autenticación por API key Bearer con comparación de tiempo constante, validación de secretos al arranque con fail-fast, separación explícita de superficie pública (demo) vs. admin, y sanitización de secretos en mensajes de error. Sin embargo, hay decisiones de **default inseguro** importantes: el webhook custom-LLM (el endpoint más caro, que dispara streaming de GPT-4o) está **sin autenticar por defecto** (`QORA_WEBHOOK_AUTH_ENABLED=false`), el CORS por defecto es `*`, el endpoint `/api/v1/tenants/{client_id}` **no exige autenticación**, y `/api/v1/demo/leads` expone PII (nombre, teléfono, notas) sin auth. La observabilidad es sólida en formato (structlog JSON) pero **carece de request/correlation ID**. No hay manejadores de excepción globales: los errores no controlados degradan al 500 plano de Starlette.

> **Nota de revisión temporal (2026-06-26):** Los "defaults inseguros" de este resumen deben leerse como **postura pre-deploy de desarrollo**, no como defectos latentes en un sistema en producción. Al cierre de la historia reconstruida (2026-06-25) **Qora todavía no está desplegado**: B2 (deploy a VPS/cloud) es el **último** ítem de Phase B, explícitamente "after security hardening" (`docs/ROADMAP.md`, tabla de fases; doc `20-historia-y-evolucion.md` §6). Las capacidades de endurecimiento — auth admin (B5, PR #107 `08e215c` / #109 `efd112c`, 2026-06-22/23), secreto de webhook **opt-in** (B6, PR #111 `61c8918`, 2026-06-23) y CORS configurable (B7, PR #111, 2026-06-23) — **ya están construidas**; lo que queda abierto son los **valores por defecto**, que deben fijarse **antes del deploy B2**. La brecha de observabilidad (request/correlation ID, manejadores de excepción globales) corresponde a **B9 — Structured logging + error monitoring**, marcada `[ ]` y señalada como la **próxima** fase planificada tras B10 (`docs/ROADMAP.md`; Engram #2142, 2026-06-25). Todos los hallazgos concretos de este documento **siguen siendo válidos** y se leen mejor como "**cerrar antes del deploy B2**". Capability ≠ enforcement por defecto (doc 20 §4, §6).

---

## 2. Seguridad

### 2.1 Autenticación admin (API key Bearer)

- El esquema de auth admin vive en `backend/app/core/auth.py` → `require_api_key()`. Lee `Authorization: Bearer <key>` y compara contra `settings.qora_api_key` con `secrets.compare_digest` (tiempo constante, sin canal lateral de timing). **[Confirmado por codigo]** (`backend/app/core/auth.py:90-157`).
- `CallerIdentity` almacena solo un hash de auditoría (16 hex de SHA-256), nunca la key cruda. **[Confirmado por codigo]** (`auth.py:58-69`, `auth.py:154-157`).
- **Fail-closed correcto**: si `qora_api_key` es `None`, todas las rutas protegidas devuelven 401 en vez de quedar abiertas. **[Confirmado por codigo]** (`auth.py:117-123`).
- **Routers admin protegidos a nivel router** vía `dependencies=[Depends(require_api_key)]`: `clients`, `agents`, `leads`, `scheduler`, `analytics`, `crm_router`, `crm_config_router`. El router `calls` lo aplica **por endpoint** (cada ruta lleva su propio `dependencies=[Depends(require_api_key)]`). **[Confirmado por codigo]** (`clients/router.py:30`, `agents/router.py:32`, `leads/router.py:48`, `scheduler/router.py:39`, `analytics/router.py:44`, `integrations/crm_router.py:32`, `integrations/crm_config_router.py:57`, `calls/router.py:57,121,228,303,316,360`).

#### Bypass de test
- `_TESTING_BYPASS` (módulo `auth.py:50`) permite saltarse la auth; lo activa `tests/conftest.py` y solo es alcanzable bajo pytest (`PYTEST_CURRENT_TEST`). El comentario afirma que producción nunca corre bajo pytest. **[Inferido razonablemente]** — el flag es un global de módulo; si algún proceso productivo importara y seteara `_TESTING_BYPASS=True` se abriría toda la superficie admin. Riesgo bajo en la práctica, pero es un interruptor global de auth. (`auth.py:110-115`).

### 2.2 Endpoint sin autenticar: `/api/v1/tenants/{client_id}` (HALLAZGO)

- El router `tenants` **no** declara `Depends(require_api_key)` ni a nivel router ni de endpoint. `GET /api/v1/tenants/{client_id}` devuelve configuración del tenant (nombre, `agent_name`, `voice_id`, `model`, `temperature`, `max_tokens`, `tools_enabled`, `is_active`, `created_at`) para **cualquier** `client_id` sin credenciales. **[Confirmado por codigo]** (`backend/app/tenants/router.py:10,24-52`; ausencia de `require_api_key` confirmada — el archivo no lo importa).
- Severidad: **Media**. Es divulgación de información de configuración interna por tenant (enumerable por `client_id`). Está descrito como "backward-compat read-only alias" en `main.py:288`, lo que sugiere legado que quedó sin la protección que sí tienen los demás routers.

### 2.3 Webhook custom-LLM sin auth por defecto (HALLAZGO)

- El endpoint núcleo `POST /api/v1/voice/custom-llm[/...]` y `POST /api/v1/voice/{client_id}/custom-llm/chat/completions` aplican `Depends(require_webhook_secret)`, **pero** ese dependency es **no-op por defecto**: si `QORA_WEBHOOK_AUTH_ENABLED` es `false` (default), retorna sin validar nada. **[Confirmado por codigo]** (`backend/app/voice/webhook.py:539,619`; `backend/app/core/auth.py:260-294`; default en `config.py:135` `qora_webhook_auth_enabled: bool = False`).
- Consecuencia: por defecto, **cualquiera que conozca o adivine un `client_id`** puede invocar el webhook y disparar streaming de GPT-4o (segunda llamada de tool incluida), generando **gasto directo en OpenAI** y escrituras de transcript en la DB. El mismo default aplica a `POST /api/v1/voice/initiation` (`initiation.py:71`).
- Severidad: **Alta** por implicancia de costo/abuso (LLM de pago expuesto sin auth en la configuración por defecto). Mitigación documentada existe (`QORA_WEBHOOK_AUTH_ENABLED=true` + `QORA_WEBHOOK_SECRET`), pero es opt-in.

> **Nota de revisión temporal (2026-06-26):** El hecho de código (auth de webhook off por defecto) es correcto y se conserva. El *framing* se contextualiza: este `default` es **postura pre-deploy de desarrollo**, no un descuido. La capacidad de lock-down (`require_webhook_secret` con comparación de tiempo constante) se **construyó deliberadamente** en B6 — PR #111 (`61c8918`, 2026-06-23) — como **opt-in** (`QORA_WEBHOOK_AUTH_ENABLED=false`) para no romper los agentes ElevenLabs existentes hasta coordinar el secreto en el dashboard de EL (doc 20 §6, "Capability ≠ enforcement"). El producto **aún no está desplegado**: B2 (deploy) es **el último ítem de Phase B**, "after security hardening" (`docs/ROADMAP.md`; doc 20 §6). El hallazgo **sigue siendo válido y de severidad Alta**: activar el flag (`QORA_WEBHOOK_AUTH_ENABLED=true` + `QORA_WEBHOOK_SECRET`) es **requisito a cerrar antes del deploy B2**.

#### Naturaleza de la verificación de webhook
- Cuando se habilita, `require_webhook_secret` valida el header `X-Webhook-Secret` por **shared secret** con `secrets.compare_digest` (constant-time). **No es** verificación de firma HMAC del cuerpo (como hace ElevenLabs con su esquema de firma); es comparación de secreto compartido. **[Confirmado por codigo]** (`auth.py:309-329`). Es aceptable pero más débil que HMAC sobre el payload: no protege contra replay ni garantiza integridad del body. **[Inferido razonablemente]**
- Fail-closed correcto: habilitado + secreto no configurado → 401 a todo (`auth.py:296-307`), reforzado por validación al arranque en `config.py:220-245` (`validate_webhook_secret_when_enabled`).

### 2.4 Superficie pública demo (PII sin auth) (HALLAZGO)

- `backend/app/demo/router.py` es **intencionalmente auth-exempt** (documentado en su docstring, líneas 1-20). Endpoints públicos:
  - `GET /api/v1/demo/context` — devuelve `elevenlabs_agent_id`, `client_name`, `agent_name`, `demo_client_id`. No expone secretos. **[Confirmado por codigo]** (`demo/router.py:59-135`).
  - `GET /api/v1/demo/leads` — devuelve `id`, `name`, `phone`, `notes`, `custom_fields` de los leads del cliente demo, **sin autenticación**. **[Confirmado por codigo]** (`demo/router.py:142-195`).
  - `POST /api/v1/demo/sessions/{session_id}/end` — con guard de scope al `QORA_DEMO_CLIENT_ID` (rechaza sesiones de otros tenants con 403). **[Confirmado por codigo]** (`demo/router.py:212-276`).
- Severidad: **Media**. `/demo/leads` expone PII (nombre, teléfono, notas) de forma pública. El alcance está acotado por diseño al cliente configurado en `QORA_DEMO_CLIENT_ID`; el riesgo real depende de que ese cliente contenga datos ficticios. Si en producción se apunta `QORA_DEMO_CLIENT_ID` a un tenant real, se filtra PII real sin auth. **[Necesita validacion humana]** (qué cliente se usa como demo en producción).

### 2.5 CORS

- Configurado en `backend/app/main.py:382-387` con `allow_origins=_allowed_origins`, `allow_methods=["*"]`, `allow_headers=["*"]`. El origen se lee de `settings.qora_allowed_origins`, cuyo **default es `"*"`** (`config.py:141`). **[Confirmado por codigo]**.
- No se setea `allow_credentials=True`, y la auth es por header Bearer (no cookies), por lo que el wildcard CORS no expone credenciales basadas en cookie. Aun así, el default `*` permite que cualquier origen invoque la API desde un navegador. Severidad: **Baja** (mitigable por config; recomendado lista explícita en prod, como dice el comentario `main.py:375-377`).

> **Nota de revisión temporal (2026-06-26):** El default `*` es **postura pre-deploy**. Antes de B7 — PR #111 (`61c8918`, 2026-06-23) — el CORS era **allow-all hardcodeado**; #111 introdujo `QORA_ALLOWED_ORIGINS` precisamente para permitir una lista explícita en producción (doc 20 §7.6, "CORS allow-all → configurable"). La capacidad de restringir el origen **existe**; el `*` es un default de desarrollo a fijar **antes del deploy B2** (último ítem de Phase B, "after security hardening", `docs/ROADMAP.md`). Hallazgo válido como ítem pre-deploy.

### 2.6 Validación de entrada (Pydantic)

- Los cuerpos de request usan modelos Pydantic (`CustomLLMRequest`, `ElevenLabsExtraBody` en `voice/webhook.py:118-150`; `DemoContextResponse`, `DemoSessionEndRequest` en `demo/router.py`). Entrada inválida → 422 automático de FastAPI. **[Confirmado por codigo]**.
- `CustomLLMRequest` declara `model_config = {"extra": "allow"}` (acepta campos arbitrarios que mande ElevenLabs). Los campos extra se loguean y se usan solo para resolver `client_id`/`lead_id`/`conversation_id`; no llegan a SQL. Riesgo: **Bajo** (superficie de log inflada, no inyección). **[Confirmado por codigo]** (`webhook.py:150,560-561`).

### 2.7 Superficie de inyección SQL

- El acceso a datos es mayormente **ORM (SQLAlchemy async)**, no SQL crudo. **[Confirmado por codigo]**.
- Único uso notable de SQL textual con f-string: `backend/app/analytics/service.py:187` `sql = text(f"""...{agent_filter}...""")`. **No es inyectable**: lo único interpolado por f-string es `agent_filter`, que es una **constante literal** (`"AND cs.agent_id = :agent_id"`, línea 184); todos los valores de usuario (`client_id`, `agent_id`, `date_from`, `date_to`, `limit`) van como **parámetros enlazados** (`:client_id`, etc.). **[Confirmado por codigo]** (`analytics/service.py:174-211`).
- PRAGMAs de SQLite vía `text()` con literales fijos (`PRAGMA journal_mode=WAL`, `busy_timeout=5000`) — sin entrada de usuario. **[Confirmado por codigo]** (`backend/app/core/database.py:85-86`).
- Conclusión: superficie de inyección SQL **muy baja**.

### 2.8 Gestión de secretos y arranque

- `backend/app/core/config.py` (`Settings`, pydantic-settings) declara secretos como `SecretStr` (`openai_api_key`, `elevenlabs_api_key`, `qora_api_key`, `qora_webhook_secret`). **[Confirmado por codigo]** (`config.py:73,80,118,134`).
- **Fail-fast al arranque**: `validate_required_secrets` (model_validator) aborta el arranque si faltan/están vacíos/son placeholders débiles `OPENAI_API_KEY`, `ELEVENLABS_API_KEY` (CRITICAL) o `QORA_API_KEY` (HIGH). Los valores nunca aparecen en mensajes de error. **[Confirmado por codigo]** (`config.py:169-218`; helper `_validate_secret_field` `config.py:27-64`).
- Lista de placeholders débiles (`change-me-before-production`, `your-key-here`, `todo`, `xxx`, `test`, `changeme`, `replace_me`) rechazada case-insensitive. **[Confirmado por codigo]** (`config.py:11-19`).
- Credenciales por cliente (CRM) validadas al arranque por `backend/app/core/credentials.py::validate_all_integration_credentials`, que escanea `backend/clients/*/crm.yaml` y hace `sys.exit()` si una integración activa referencia una env var ausente/placeholder. Solo valida referencias ALL_CAPS (env var names); valores literales se tratan como dev/test. **[Confirmado por codigo]** (`credentials.py:80-204`).
- **Sanitización de secretos en errores**: `crm_config_router.py::_sanitize_secret_text` limpia el valor del secreto de mensajes de error antes de devolverlos. **[Confirmado por codigo]** (`integrations/crm_config_router.py:176,281,327`).

### 2.9 Secretos / DB en el repositorio

- **No hay `.env` ni secretos comprometidos en git.** `git ls-files` solo muestra `.env.example` y `frontend/.env.example` (nombres de variables, sin valores). El historial (`git log --all --diff-filter=A`) tampoco contiene `.env` ni `qora.db`. **[Confirmado por codigo]**.
- `.gitignore` excluye `.env`, `*.env`, `*.db`, `*.db-shm`, `*.db-wal`, `*.db.bak-*` (`.gitignore:19-27,71`). **[Confirmado por codigo]**.
- `backend/qora.db` (758 KB) y `backend/qora.db.bak-20260619` (758 KB) **existen en el working tree pero están gitignored y NO trackeados** (`git check-ignore` confirma ambos; `git ls-files` no los lista). El riesgo de "DB commiteada" es por tanto **bajo a nivel repo**; el riesgo real es local: una DB SQLite poblada con datos reales presente en el entorno de desarrollo, fuera del control de versiones. **[Confirmado por codigo]** / **[Necesita validacion humana]** (si esa DB contiene datos personales reales).
- `.env.example` solo expone **nombres** de variables: `OPENAI_API_KEY`, `ELEVENLABS_API_KEY`, `QORA_API_KEY`, `QUINTANA_AIRTABLE_API_KEY`, `ELEVENLABS_VOICE_ID`, `ELEVENLABS_AGENT_ID`. Sin valores. **[Confirmado por codigo]**.
- Existe `backend/scripts/check-secrets.py` (CLI argparse) que escanea variables requeridas y crm.yaml para detectar secretos faltantes/placeholder y dead vars. Herramienta de preflight, no parte del runtime. **[Confirmado por codigo]** (`scripts/check-secrets.py:111-323`).

### 2.10 Endpoints públicos / sin auth (inventario)

| Endpoint | Auth | Notas |
|---|---|---|
| `GET /api/v1/health` | Pública | Solo status/uptime/version. OK. `main.py:259-267` |
| `GET /api/v1/tenants/{client_id}` | **Sin auth** | Divulga config de tenant. HALLAZGO 2.2 |
| `GET /api/v1/demo/context` | Pública (diseño) | Sin secretos. `demo/router.py:59` |
| `GET /api/v1/demo/leads` | **Sin auth** | Expone PII. HALLAZGO 2.4 |
| `POST /api/v1/demo/sessions/{id}/end` | Pública (diseño) | Scope-guard a demo client. `demo/router.py:212` |
| `POST /api/v1/voice/custom-llm*` | Webhook auth **off por defecto** | Dispara GPT-4o. HALLAZGO 2.3 |
| `POST /api/v1/voice/initiation` | Webhook auth **off por defecto** | `initiation.py:71` |
| `GET /api/v1/voice/signed-url` | **Sin auth** | Usa `ELEVENLABS_API_KEY` server-side; no la expone, devuelve `signed_url`. `webhook.py:76-110` |
| `GET /admin`, `/{full_path}` | Pública | Redirect / SPA fallback. `main.py:414,456` |

- `GET /api/v1/voice/signed-url` no tiene auth y genera una signed URL de WebSocket de ElevenLabs llamando a la API de EL con la api key del servidor. No filtra la key, pero permite a cualquiera generar URLs firmadas (consumo de cuota EL). Severidad: **Baja-Media**. **[Confirmado por codigo]** (`webhook.py:76-110`).

---

## 3. Observabilidad

### 3.1 Logging estructurado (structlog JSON)

- `backend/app/core/logging.py::setup_logging` configura structlog con pipeline: `merge_contextvars` → `add_log_level` → `StackInfoRenderer` → `set_exc_info` → `TimeStamper(iso)` → `JSONRenderer`. Salida JSON por línea vía `PrintLoggerFactory`. **[Confirmado por codigo]** (`logging.py:21-36`).
- Nivel configurable por `settings.log_level` (validado contra `{DEBUG,INFO,WARNING,ERROR,CRITICAL}` en `config.py:160-167`). **[Confirmado por codigo]**.
- `cache_logger_on_first_use=False` — se re-resuelve el logger en cada uso (ligero costo, evita capturar config previa). **[Confirmado por codigo]** (`logging.py:35`).

### 3.2 Logging de requests/errores

- `RequestLoggingMiddleware` (`main.py:69-106`) loguea `request_started` (method, path) y `request_completed` (method, path, status_code, latency_ms). En excepción no controlada loguea `request_error` con `error_type`, `error_message`, `latency_ms`, `exc_info=True` y **re-lanza** la excepción. **[Confirmado por codigo]**.
- **No loguea headers ni Authorization** → no filtra el Bearer token. **[Confirmado por codigo]**.
- El webhook custom-LLM sí loguea el cuerpo: `elevenlabs_request_received` con `body_keys`, `extra_body` (model_dump completo → incluye `client_id`, `lead_id`, `conversation_id`) y `extra_fields` (todo `model_extra`). PII de bajo nivel (ids), no secretos. Severidad: **Baja**. **[Confirmado por codigo]** (`webhook.py:553-563`).
- El pipeline de jobs/voz loguea eventos consistentes: `job_enqueued`, `job_started`, `job_completed`, `job_failed`, `job_dead`, `job_will_retry`, `llm_stream_timeout`, `stream_error`, `voice_context_*_failed`, etc. **[Confirmado por codigo]** (`jobs/executor.py`, `voice/webhook.py`).

### 3.3 Correlation / Request IDs (BRECHA)

- `merge_contextvars` está en el pipeline (capaz de inyectar `session_id` u otros contextvars), **pero no se encontró ningún binding de `request_id`/`correlation_id`/`trace_id`** (`rg request_id|correlation|bind_contextvars|X-Request-ID` no devolvió resultados en `backend/app`). **[Confirmado por codigo]** (búsqueda vacía).
- Consecuencia: los logs de un mismo request (`request_started`, eventos de negocio, `request_completed`) **no comparten un id de correlación**; la trazabilidad end-to-end depende de campos ad-hoc como `session_id`/`conversation_id` cuando están presentes. Severidad observabilidad: **Media** (dificulta el debugging en producción multi-tenant). **[Inferido razonablemente]**

> **Nota de revisión temporal (2026-06-26):** Esta brecha no es un olvido aislado: el correlation/request ID cae dentro de **B9 — Structured logging + error monitoring**, marcada `[ ]` y señalada como la **próxima** fase planificada tras B10 (`docs/ROADMAP.md`; Engram #2142, 2026-06-25). El `jobs/queries.py` introducido en B10 PR 2b (#121, `90e4103`, 2026-06-25) es **groundwork** explícito de B9 (doc 20 §6). El hallazgo sigue vigente como ítem a cubrir en B9, antes del deploy B2.

### 3.4 Health endpoint

- `GET /api/v1/health` devuelve `{status, uptime_seconds, version}` (versión hardcodeada `_APP_VERSION = "0.1.0"`, `main.py:256`). No verifica DB ni dependencias externas (es un liveness, no readiness). **[Confirmado por codigo]** (`main.py:259-267`). Sin chequeo de DB/ElevenLabs/OpenAI, un health "healthy" no garantiza que el servicio pueda operar. Severidad: **Baja**.

---

## 4. Manejo de errores

### 4.1 Manejadores de excepción globales (AUSENTES)

- **No hay `add_exception_handler` ni `@app.exception_handler` en todo `backend/app`** (`rg exception_handler` vacío). **[Confirmado por codigo]**.
- Por tanto: excepciones no controladas → 500 plano de Starlette ("Internal Server Error"). `HTTPException` lanzadas explícitamente producen el JSON estándar de FastAPI con el `detail` provisto. No hay forma de error unificada propia. Severidad: **Media**. **[Inferido razonablemente]**

> **Nota de revisión temporal (2026-06-26):** La ausencia de manejadores de excepción globales y de una forma de error unificada cae dentro del alcance de **B9 — Structured logging + error monitoring**, la próxima fase planificada tras B10 (`docs/ROADMAP.md`; Engram #2142, 2026-06-25), no es un descuido aislado. Hallazgo válido a resolver en B9 (antes del deploy B2).

### 4.2 Forma de respuesta de error (inconsistente)

- Las `HTTPException` del código usan `detail` como **dict** con forma `{"error": "...", "message": "..."}` en auth (`auth.py:120-152,298-329`) y a veces `{"error": "..."}` plano en voz/tenants (`webhook.py:584,876,885`; `tenants/router.py:39`). Los 422 de validación Pydantic usan la forma estándar de FastAPI (`{"detail": [...]}`). **[Confirmado por codigo]**.
- No hay esquema de error canónico único en toda la API. Severidad: **Baja** (consistencia/DX).

### 4.3 Degradación elegante en la ruta de voz (SSE)

- La ruta custom-LLM degrada con cuidado para no romper la llamada de voz:
  - Timeout por turno de LLM: `asyncio.timeout(60.0)`; al expirar persiste el transcript parcial y emite `_sse_stop()` + `_sse_done()` en vez de error. **[Confirmado por codigo]** (`webhook.py:297-298,484-504`).
  - Fallo de render de contexto → usa `SAFE_CONTEXT_RENDER_FAILURE_PROMPT` (disculpa genérica) en vez de romper. **[Confirmado por codigo]** (`webhook.py:63-66,1008-1019`).
  - Sin agente configurado → stream SSE con mensaje al usuario en vez de 500. **[Confirmado por codigo]** (`webhook.py:1207-1230`).
  - Errores de persistencia de transcript/tool se capturan y loguean como `warning` sin abortar el stream (`except Exception ... noqa: BLE001`). **[Confirmado por codigo]** (`webhook.py:440-445,496-501,511-516`).
  - Excepción genérica en el generador → loguea `stream_error` y cierra el stream limpiamente. **[Confirmado por codigo]** (`webhook.py:1296-1299`).
- Observación: el `except Exception` en `_execute_tool` devuelve `{"error": str(exc)}` que luego se serializa al LLM; un mensaje de excepción podría llegar al contexto del modelo. Riesgo bajo de fuga, pero no es un canal pensado para detalles internos. **[Inferido razonablemente]** (`webhook.py:248-249`).

### 4.4 Reintentos en jobs en background (durable executor)

- `backend/app/jobs/executor.py::JobExecutor` implementa una máquina de estados durable (DB-backed) con reintentos: `pending → running → completed | failed | dead`. **[Confirmado por codigo]**.
- Backoff exponencial con jitter, cap 60s: `calculate_backoff(attempt)` = `min(base·2^attempt + rand(0,jitter), max_delay)`. **[Confirmado por codigo]** (`executor.py:42-66`).
- Política de error: `ConfigurationError` → máx 1 retry, luego `dead` con `operator_review=True`; otras excepciones → retry hasta `max_attempts` (default 3) y luego `dead`. El error se persiste en `job.error` (audit trail) en cada fallo. **[Confirmado por codigo]** (`executor.py:282-360`).
- Sesión DB **fresca por intento** (evita sesión envenenada bloqueando reintentos). **[Confirmado por codigo]** (`executor.py:266-280`).
- Recuperación al arranque: `recover()` re-encola jobs `pending`/`running` tras un crash, reseteando `running→pending` para evitar doble disparo; con guard de idempotencia `_active_job_ids`. **[Confirmado por codigo]** (`executor.py:386-439`).
- **Importante**: todo el executor está detrás del flag `ENABLE_JOB_EXECUTOR` (default **`false`**). Con el flag apagado, los jobs post-call siguen la ruta legacy fire-and-forget (`asyncio.create_task`) sin durabilidad ni reintentos. **[Confirmado por codigo]** (`config.py:152`; `main.py:198-204`). El comportamiento durable descrito **no está activo por defecto**. **[Necesita validacion humana]** (si el flag está activado en producción).
- `shutdown()` cancela tareas activas sin drain graceful (decisión MVP documentada). Jobs en vuelo durante shutdown se cancelan y se recuperan al próximo arranque. **[Confirmado por codigo]** (`executor.py:441-455`).

### 4.5 Tareas de fondo del ciclo de vida

- `lifespan` arranca tareas: `_session_store_cleanup_task` (TTL sesiones in-memory cada 60s), `stale_session_sweeper`, `scheduler_tick`, y opcionalmente recovery del executor. Todas se cancelan en shutdown con `try/except asyncio.CancelledError`. **[Confirmado por codigo]** (`main.py:114-126,206-246`). El store de sesiones in-memory tiene limpieza por TTL, mitigando memory leaks de conversaciones abandonadas. **[Confirmado por codigo]**.

---

## 5. Diagrama — superficie de auth por endpoint

```mermaid
flowchart TD
    Req[HTTP Request] --> MW[RequestLoggingMiddleware<br/>log method/path/latency]
    MW --> CORS[CORSMiddleware<br/>default allow_origins=*]
    CORS --> R{Router}
    R -->|clients/agents/leads/calls<br/>scheduler/analytics/crm| ADM[require_api_key<br/>Bearer + compare_digest]
    R -->|tenants/{id}| NOAUTH1[SIN AUTH<br/>HALLAZGO 2.2]
    R -->|demo/*| NOAUTH2[Auth-exempt por diseño<br/>demo/leads expone PII 2.4]
    R -->|voice/custom-llm<br/>voice/initiation| WH[require_webhook_secret<br/>no-op si AUTH_ENABLED=false<br/>HALLAZGO 2.3]
    R -->|health, signed-url| PUB[Pública]
    ADM --> H[Handler]
    NOAUTH1 --> H
    NOAUTH2 --> H
    WH --> H
    PUB --> H
    H -.->|excepción no controlada| ERR[500 plano Starlette<br/>sin exception_handler global 4.1]
```

---

## 6. Hallazgos de seguridad (con severidad)

| # | Hallazgo | Severidad | Evidencia |
|---|---|---|---|
| S1 | Webhook custom-LLM e initiation sin auth por defecto (`QORA_WEBHOOK_AUTH_ENABLED=false`) → GPT-4o disparable por cualquiera que sepa un `client_id`; abuso de costo OpenAI | **Alta** | `config.py:135`; `auth.py:292-294`; `webhook.py:539,619` |
| S2 | `GET /api/v1/tenants/{client_id}` sin autenticación → divulga config de tenant, enumerable | **Media** | `tenants/router.py:24-52` (sin `require_api_key`) |
| S3 | `GET /api/v1/demo/leads` expone PII (name, phone, notes) sin auth | **Media** | `demo/router.py:142-195` |
| S4 | CORS default `allow_origins=["*"]` | **Baja-Media** | `main.py:379-387`; `config.py:141` |
| S5 | Webhook usa shared-secret header (no firma HMAC del body) → sin protección anti-replay/integridad | **Baja-Media** | `auth.py:309-329` |
| S6 | `GET /api/v1/voice/signed-url` sin auth → genera signed URLs de EL (consumo de cuota) | **Baja-Media** | `webhook.py:76-110` |
| S7 | `_TESTING_BYPASS` es un flag global de módulo que desactiva toda la auth admin | **Baja** | `auth.py:50,110-115` |
| S8 | Mensaje de excepción de tool puede llegar al contexto del LLM (`{"error": str(exc)}`) | **Baja** | `webhook.py:248-249,465` |
| S9 | DB SQLite poblada en working tree (`qora.db`, `.bak`) — gitignored, no commiteada, pero con datos locales | **Baja** | `git check-ignore` OK; `backend/qora.db` 758 KB |

**Aspectos positivos** (no son hallazgos): comparación constant-time en auth y webhook; fail-fast de secretos al arranque; `SecretStr` para todos los secretos; sanitización de secretos en errores CRM; hash de auditoría en vez de key cruda; fail-closed cuando falta config de auth; no hay secretos en git ni en historial; superficie de inyección SQL mínima (ORM + bind params).

> **Nota de revisión temporal (2026-06-26):** Los hallazgos de esta tabla se conservan **sin cambios de hecho ni de severidad**. Contexto de framing: **S1** (webhook off por defecto) y **S4** (CORS `*`) son **defaults de desarrollo pre-deploy** — la capacidad de lock-down se construyó en B5/B6/B7 (PR #107 `08e215c`, #109 `efd112c`, #111 `61c8918`, 2026-06-22/23) y los valores deben fijarse **antes del deploy B2** (último ítem de Phase B, "after security hardening", `docs/ROADMAP.md`; doc 20 §6). Las brechas de observabilidad (§3.3) y de manejadores globales (§4.1) corresponden a **B9 — Structured logging + error monitoring**, la próxima fase planificada (Engram #2142, 2026-06-25). Todos siguen siendo **requisitos a cerrar antes de B2**.

---

## 7. Cobertura y límites

- **No ejecutado**: no se corrió la app, ni tests, ni se inspeccionó tráfico real. Todo se infiere del código estático (read-only). **[Necesita validacion humana]**
- **Valores de `.env` de producción**: no auditados (no existen en el repo). No se puede confirmar si `QORA_WEBHOOK_AUTH_ENABLED`, `ENABLE_JOB_EXECUTOR`, `QORA_ALLOWED_ORIGINS`, `QORA_DOCS_ENABLED` o `QORA_DEMO_CLIENT_ID` tienen valores seguros en el entorno desplegado. **[Necesita validacion humana]**
- **Contenido de `backend/qora.db`**: no inspeccionado (no se abre la DB); se desconoce si contiene PII real o datos de prueba. **[Necesita validacion humana]**
- **Configuración de ElevenLabs**: si el webhook secret está realmente seteado en el dashboard de EL y si se usa el esquema de firma HMAC nativo de EL (no auditado, fuera del repo). **[Necesita validacion humana]**
- **Despliegue / reverse proxy**: se desconoce si hay un WAF, rate-limiting, o gateway delante que mitigue S1/S6 (no hay rate-limiting visible en el código). **[Necesita validacion humana]**
- **Frontend**: la auditoría se centró en backend; no se verificó cómo el frontend almacena/envía `QORA_API_KEY`. **[Necesita validacion humana]**
- **Cobertura de scope**: se cubrió auth/authorization, secretos en repo, validación de entrada, inyección SQL, CORS, verificación de webhook, endpoints públicos, riesgo de DB commiteada, logging/structlog, request IDs, health, manejadores globales, forma de error y reintentos de jobs/voz. Scope completo.
