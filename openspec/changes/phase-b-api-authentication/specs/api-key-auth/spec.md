# API Key Auth Specification

## Purpose

Static bearer token authentication for all Qora admin API surfaces. Protects routes that read PII, mutate tenant state, or generate billable third-party calls without introducing user models or JWT.

## Requirements

### Requirement: Bearer Token Enforcement

All admin API routes MUST require a valid `Authorization: Bearer <key>` header. The system MUST reject requests with a missing, malformed, or incorrect token with HTTP 401 before any handler logic executes.

The system MUST validate the token using a constant-time comparison to prevent timing attacks. The comparison MUST NOT add measurable latency to request processing.

#### Scenario: Valid bearer token on admin route

- GIVEN a configured `QORA_API_KEY` env var and a request with `Authorization: Bearer <correct-key>`
- WHEN the request reaches any admin router
- THEN the system returns the route's normal response (2xx or relevant success code)

#### Scenario: Missing authorization header

- GIVEN a request to any admin route with no `Authorization` header
- WHEN the authentication check runs
- THEN the system returns HTTP 401 with no handler side-effects

#### Scenario: Incorrect token value

- GIVEN a request with `Authorization: Bearer <wrong-key>`
- WHEN the authentication check runs
- THEN the system returns HTTP 401; the comparison MUST take constant time regardless of token length

### Requirement: Explicit Auth Exclusions

The following paths MUST remain accessible without authentication:

| Path pattern | Reason |
|---|---|
| `/api/v1/health` | Docker and orchestrator health checks |
| `/docs`, `/redoc` | OpenAPI docs (controlled by `QORA_DOCS_ENABLED`) |
| `/demo` static files | Public demo surface |

#### Scenario: Health check without auth

- GIVEN a running Qora backend with auth enabled
- WHEN `GET /api/v1/health` is called without any header
- THEN the system returns HTTP 200

#### Scenario: OpenAPI docs visibility

- GIVEN `QORA_DOCS_ENABLED=true`
- WHEN `GET /docs` is accessed without auth
- THEN the docs page loads (HTTP 200); no API key is exposed in the schema

### Requirement: Config-Driven Secret

The API key MUST be read from `QORA_API_KEY` environment variable at startup. The value MUST be treated as a secret string (not logged, not exposed in responses or error bodies). The system MUST fail startup or return 503 if `QORA_API_KEY` is not configured in a production environment.

#### Scenario: Missing env var in production

- GIVEN `QORA_API_KEY` is not set in the environment
- WHEN the backend starts (production mode)
- THEN startup fails with a clear configuration error; no routes are served

#### Scenario: Key rotated between requests

- GIVEN the env var is updated and the process restarted
- WHEN requests arrive with the old key
- THEN they receive HTTP 401; requests with the new key receive 200

### Requirement: Phase C Extension Point

The auth dependency MUST be designed so that replacing static bearer auth with JWT requires only swapping the dependency implementation, with zero changes to router signatures or handler code.

#### Scenario: Dependency swappability

- GIVEN the `require_api_key` FastAPI dependency is in use
- WHEN Phase C introduces `require_jwt`
- THEN all routers that declared `Depends(require_api_key)` can adopt `require_jwt` by changing only the dependency reference — no handler parameters change
