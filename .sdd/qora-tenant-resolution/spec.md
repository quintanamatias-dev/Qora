# Delta Spec: qora-tenant-resolution

**Change**: qora-tenant-resolution
**Date**: 2026-04-18
**Status**: Draft

---

## CAP-1: Path-Based Tenant Resolution (NEW)

### Requirement: POST /api/v1/voice/{client_id}/custom-llm/chat/completions

The system MUST expose `POST /api/v1/voice/{client_id}/custom-llm/chat/completions` that extracts `client_id` from the URL path parameter.

The handler MUST return HTTP 404 (not 422) if `client_id` does not match any registered tenant.

The handler MUST emit a structured log event `custom_llm_path_request` containing: `client_id`, `conversation_id` (if present in body, else `null`), `message_count`, and `model`. Rationale: these fields provide more actionable observability than a raw byte size — message count and model directly correlate with latency and cost, which are the primary operational concerns for this endpoint.

If `client_id` is present in both the URL path and the request body, the path value MUST take precedence. If the two values differ, the handler MUST additionally emit a `client_id_mismatch` warning log event (including both values) but MUST continue using the path value.

#### Scenario: Happy path — valid tenant, returns SSE stream

- GIVEN tenant `quintana-seguros` exists in DB
- WHEN `POST /api/v1/voice/quintana-seguros/custom-llm/chat/completions` is called with a valid body
- THEN HTTP 200 is returned with `Content-Type: text/event-stream`
- AND a `custom_llm_path_request` log event is emitted with `client_id = "quintana-seguros"`

#### Scenario: Unknown tenant in path — returns 404

- GIVEN `ghost-client` does NOT exist in DB
- WHEN `POST /api/v1/voice/ghost-client/custom-llm/chat/completions` is called
- THEN HTTP 404 is returned with body `{"error": "client not found"}`
- AND no SSE stream is started

#### Scenario: Path client_id takes precedence over body client_id

- GIVEN tenant `quintana-seguros` exists in DB
- AND the request body contains `"client_id": "quintana-seguros"`
- WHEN `POST /api/v1/voice/quintana-seguros/custom-llm/chat/completions` is called
- THEN the handler resolves tenant as `quintana-seguros` (path value)
- AND HTTP 200 is returned normally

#### Scenario: client_id mismatch — path wins, warning logged

- GIVEN tenant `quintana-seguros` exists in DB
- AND the request body contains `"client_id": "other-client"`
- WHEN `POST /api/v1/voice/quintana-seguros/custom-llm/chat/completions` is called
- THEN the handler uses `quintana-seguros` (path value) for tenant resolution
- AND a `client_id_mismatch` warning is logged with both `path_value = "quintana-seguros"` and `body_value = "other-client"`
- AND HTTP 200 is returned

#### Scenario: Missing /chat/completions suffix — 404 via routing

- WHEN `POST /api/v1/voice/quintana-seguros/custom-llm` is called (no `/chat/completions`)
- THEN HTTP 404 is returned by FastAPI routing (no route match)

#### Scenario: Invalid tenant format in path — 404

- GIVEN no tenant with `id = "INVALID!!TENANT"` exists in DB
- WHEN `POST /api/v1/voice/INVALID!!TENANT/custom-llm/chat/completions` is called
- THEN HTTP 404 is returned with `{"error": "client not found"}`

#### Scenario: Concurrent requests for different tenants — no cross-contamination

- GIVEN `quintana-seguros` and `demo-inmobiliaria` both exist in DB
- WHEN simultaneous requests are made to each tenant's path-based route
- THEN each response uses only its own tenant's `CallSession` and config
- AND no fields from one session appear in the other's response

---

## CAP-2: Legacy Route Deprecation (MODIFIED — modifies CAP-6 from qora-phase1)

### Requirement: Strict client_id Resolution in Webhook

**Previously**: The route `POST /api/v1/voice/custom-llm/chat/completions` resolved `client_id` from `elevenlabs_extra_body.client_id` → top-level field → `model_extra`, returning HTTP 422 if all sources were null, and HTTP 404 if `client_id` was present but not in DB.

The legacy route `POST /api/v1/voice/custom-llm/chat/completions` MUST remain functional for backward compatibility. Its body-based `client_id` resolution logic (unchanged from CAP-6): `elevenlabs_extra_body.client_id` → top-level `client_id` field → `model_extra`. If `client_id` is absent after all sources, MUST return HTTP 422. If present but not in DB, MUST return HTTP 404.

On EVERY successful request to this route, the handler MUST emit a `custom_llm_legacy_route_used` warning log event containing: `client_id` (resolved value) and a hint string pointing to the new path-based route.

The ElevenLabs initiation webhook URL MUST include `?client_id={client_id}` as a query parameter. The web demo MUST always send `client_id` in `dynamic_variables`.

#### Scenario: Legacy route — client_id in elevenlabs_extra_body — works, logs deprecation

- GIVEN `quintana-seguros` exists in DB
- AND the request body contains `elevenlabs_extra_body.client_id = "quintana-seguros"`
- WHEN `POST /api/v1/voice/custom-llm/chat/completions` is called
- THEN HTTP 200 is returned with an SSE stream
- AND a `custom_llm_legacy_route_used` warning is logged with `client_id = "quintana-seguros"` and a migration hint

#### Scenario: Legacy route — client_id as top-level field — works, logs deprecation

- GIVEN `quintana-seguros` exists in DB
- AND the request body contains top-level `"client_id": "quintana-seguros"`
- WHEN `POST /api/v1/voice/custom-llm/chat/completions` is called
- THEN HTTP 200 is returned
- AND a `custom_llm_legacy_route_used` warning is logged

#### Scenario: Legacy route — no client_id anywhere — returns 422

- GIVEN no `client_id` is present in any field of the request body
- WHEN `POST /api/v1/voice/custom-llm/chat/completions` is called
- THEN HTTP 422 is returned
- AND no `custom_llm_legacy_route_used` event is emitted

#### Scenario: Legacy route — deprecation warning includes migration hint

- GIVEN any valid request to the legacy route
- WHEN the handler emits `custom_llm_legacy_route_used`
- THEN the log event's `migration_hint` field contains the string `"/api/v1/voice/{client_id}/custom-llm/chat/completions"`

> **Note**: Implementation uses `migration_hint` for clarity; spec aligned. Same pattern as `message_count` alignment in CAP-1 (prefer descriptive field names over ambiguous short names).

#### Scenario: client_id resolves to valid client (unchanged from CAP-6)

- GIVEN `client_id = "quintana-seguros"` is in `elevenlabs_extra_body`
- WHEN the legacy webhook is called
- THEN the request proceeds normally with that client's config

#### Scenario: client_id absent — 422 (unchanged from CAP-6)

- GIVEN no `client_id` is present in any field of the request
- WHEN `/api/v1/voice/custom-llm` is called
- THEN HTTP 422 is returned

#### Scenario: client_id not found in DB — 404 (unchanged from CAP-6)

- GIVEN `client_id = "ghost-client"` is sent but does not exist in DB
- WHEN the legacy webhook is called
- THEN HTTP 404 is returned with `{"error": "client not found"}`

#### Scenario: Initiation webhook — client_id missing — 422 (unchanged from CAP-6)

- GIVEN no `client_id` query param or body field
- WHEN `POST /api/v1/voice/initiation` is called
- THEN HTTP 422 is returned

---

## CAP-3: Structural Consistency (NEW)

### Requirement: Shared Handler Implementation

Both `POST /api/v1/voice/{client_id}/custom-llm/chat/completions` and `POST /api/v1/voice/custom-llm/chat/completions` MUST share the same downstream handler implementation. The ONLY difference between routes MUST be how `client_id` is resolved (path param vs. body extraction). No business logic, session creation, or SSE formatting code MAY be duplicated.

Both routes MUST emit the same downstream events: session creation (`CallSession` record), transcript turns, and SSE chunk format.

### Requirement: Identical Downstream Behavior

Given the same resolved `client_id` and request body, both routes MUST produce identical `CallSession` records, SSE chunk shapes, and tool call behavior.

#### Scenario: Both routes create identical CallSession records

- GIVEN `quintana-seguros` exists and the same messages array is sent via both routes
- WHEN each route processes the request
- THEN both `CallSession` records have identical `client_id`, `lead_id`, and `messages` content
- AND the only difference is the `client_id` resolution source (logged field)

#### Scenario: Both routes emit the same SSE chunk format

- GIVEN valid requests to both routes for the same tenant
- WHEN the SSE stream is consumed
- THEN each `data:` chunk has the same JSON shape (e.g., `{"id": ..., "choices": [...]}`)

#### Scenario: Tool calls work identically on both routes

- GIVEN a request body that triggers a tool call (e.g., `get_lead_info`)
- WHEN the request is made to either route for the same tenant
- THEN tool call execution, result injection, and streaming continuation are identical
