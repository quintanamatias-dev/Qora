# Observability Health Readiness Specification

## Purpose

`GET /api/v1/health` currently returns liveness only (`status`, `uptime_seconds`, `version`).
B9 extends it with an optional `?detail=true` query parameter that adds DB connectivity
and job executor status signals so operators and deploy scripts can verify readiness
without requiring a full operator dashboard.

## Requirements

### Requirement: Health Endpoint — Liveness (Existing Behaviour Preserved)

`GET /api/v1/health` (without `?detail=true`) MUST continue to return the current
liveness response (`status`, `uptime_seconds`, `version`) unchanged, with no additional latency.

#### Scenario: Liveness-only call is unchanged

- GIVEN the application is running
- WHEN `GET /api/v1/health` is called without query parameters
- THEN the response status is 200
- AND the body includes `status`, `uptime_seconds`, and `version`
- AND no DB ping or job executor check is performed

---

### Requirement: Health Endpoint — Detail Mode

`GET /api/v1/health?detail=true` MUST return the liveness fields PLUS:
- `db`: `"ok"` if a DB ping succeeds, `"error"` with a message if it fails.
- `job_executor`: `"running"` if the executor is active, `"stopped"` if not.

The response MUST complete within a 2-second timeout; if the DB ping exceeds the
timeout the `db` field MUST report `"timeout"` rather than blocking indefinitely.

#### Scenario: All dependencies healthy

- GIVEN the DB is reachable and the job executor is running
- WHEN `GET /api/v1/health?detail=true` is called
- THEN the response status is 200
- AND the body includes `db: "ok"` and `job_executor: "running"`

#### Scenario: DB unreachable returns degraded status

- GIVEN the DB is unreachable
- WHEN `GET /api/v1/health?detail=true` is called
- THEN the response status is 200 (the endpoint itself is healthy)
- AND the body includes `db: "error"` with a non-empty `db_error` message
- AND `job_executor` is still reported accurately

#### Scenario: DB ping times out

- GIVEN the DB ping does not respond within 2 seconds
- WHEN `GET /api/v1/health?detail=true` is called
- THEN the response body includes `db: "timeout"`
- AND the endpoint returns within 2.5 seconds total (not blocked indefinitely)

#### Scenario: Job executor stopped returns degraded status

- GIVEN `ENABLE_JOB_EXECUTOR=false` or the executor has not started
- WHEN `GET /api/v1/health?detail=true` is called
- THEN the response body includes `job_executor: "stopped"`
- AND the response status is 200

---

### Requirement: Health Endpoint — Response Schema

The `?detail=true` response MUST conform to a documented JSON schema so deploy scripts
and future dashboards can parse it reliably.

| Field | Type | Always present | Description |
|---|---|---|---|
| `status` | `str` | YES | Existing liveness status value, currently `"healthy"` |
| `uptime_seconds` | `float` | YES | Seconds since startup |
| `version` | `str` | YES | App version string |
| `db` | `str` | Only with `?detail=true` | `"ok"` \| `"error"` \| `"timeout"` |
| `db_error` | `str \| null` | Only when `db != "ok"` | Error detail |
| `job_executor` | `str` | Only with `?detail=true` | `"running"` \| `"stopped"` |

#### Scenario: Detail response matches schema contract

- GIVEN all dependencies are healthy
- WHEN `GET /api/v1/health?detail=true` is called and response is parsed
- THEN every field in the schema table above is present with the correct type
- AND no extra undocumented fields appear at the top level

---

### Requirement: Health Endpoint — No Auth Required

The health endpoint MUST NOT require authentication or API keys, as it MUST be
callable by load balancers, deploy scripts, and monitoring agents without credentials.

#### Scenario: Health endpoint is reachable without credentials

- GIVEN the application is running with auth middleware active
- WHEN `GET /api/v1/health?detail=true` is called with no Authorization header
- THEN the response status is 200 (not 401 or 403)
