# Tenant Isolation Specification

## Purpose

Every admin API route that accepts or operates on tenant-scoped data (identified by `client_id`) MUST verify that the caller is authorized for that tenant. Prevents one authenticated caller from reading or mutating another tenant's data. Qora is the source of truth for client/agent identity and tenant routing; ElevenLabs has no role in tenant isolation.

## Requirements

### Requirement: Tenant Scope Enforcement on Admin Routes

Admin routes that accept a `client_id` parameter MUST verify that the authenticated caller is authorized to access that tenant's data. For the B5 single-operator MVP, one global `QORA_API_KEY` covers all tenants. The enforcement layer MUST be designed so per-tenant keys can be added later without changing router signatures.

#### Scenario: Authorized caller accesses own tenant data

- GIVEN a valid bearer token and a request scoped to `client_id=X`
- WHEN the admin route handles the request
- THEN the response returns data for `client_id=X` only

#### Scenario: Caller attempts cross-tenant access (future per-tenant keys)

- GIVEN a valid bearer token scoped to `client_id=X` and a request for `client_id=Y`
- WHEN the tenant isolation check runs
- THEN the system returns HTTP 403; no data for `client_id=Y` is returned or mutated

### Requirement: Qora as Source of Truth for Client/Agent Identity

Qora's own `Client` and `Agent` DB records MUST be the authoritative source for client/agent identity and tenant routing. ElevenLabs IDs (`elevenlabs_agent_id`) are stored in Qora's Agent record and are treated as voice-pipeline configuration only — they do not determine tenant identity.

#### Scenario: Agent identity resolved from Qora DB

- GIVEN an incoming voice initiation with a `client_id`
- WHEN the system resolves session context
- THEN `client_id`, `agent_id`, and related identity are read from Qora's DB; ElevenLabs is not queried for identity purposes

### Requirement: Response Data Scoping

Admin route responses MUST NOT return data belonging to tenants other than the one the caller is authorized for. Query results, list endpoints, and aggregations MUST be filtered to the caller's authorized tenant scope.

#### Scenario: List endpoint returns only authorized tenant data

- GIVEN an authenticated request to a list endpoint (e.g., `/api/v1/leads`)
- WHEN the route executes
- THEN only records belonging to the caller's authorized `client_id` scope are returned

#### Scenario: Direct resource access for unauthorized tenant

- GIVEN an authenticated request for a resource (e.g., `/api/v1/leads/{lead_id}`) where `lead_id` belongs to a different tenant
- WHEN the request is processed
- THEN the system returns HTTP 403 or HTTP 404 (no data leakage)
