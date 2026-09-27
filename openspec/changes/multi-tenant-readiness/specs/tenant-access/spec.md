# Tenant Access Specification (delta over `tenant-isolation`)

## Purpose

Make the tenant-isolation requirements enforceable for principals scoped to a
subset of tenants, and close routes that bypass authentication.

## Requirements

### Requirement: Principal Roles

Every authenticated admin request MUST resolve to a principal with role
`superadmin` (all tenants) or `client` (an explicit set of tenant ids). The
operator API key MUST resolve to `superadmin`.

### Requirement: Explicit Tenant Scope

A route that receives `client_id` in its path or query MUST return 403
`tenant_forbidden` when the principal cannot access that tenant, before any
tenant data is read or written.

#### Scenario: Client principal requests another tenant's leads

- GIVEN a principal scoped to tenant A
- WHEN it requests `GET /api/v1/leads?client_id=B`
- THEN the response is 403

### Requirement: Resource Ownership

A route that addresses a resource by id MUST verify that the resource's
`client_id` is accessible to the principal and MUST respond exactly as if the
resource did not exist (404) otherwise.

#### Scenario: Cross-tenant call transcript

- GIVEN a principal scoped to tenant A and a call session of tenant B
- WHEN it requests `GET /api/v1/calls/{session_id}/transcript`
- THEN the response is 404

### Requirement: Superadmin-only Administration

Client lifecycle (list all, create, update, delete), agent writes, integration
writes, entitlement writes, and signed-URL minting MUST require `superadmin`.

#### Scenario: Client principal lists clients

- GIVEN a principal scoped to tenant A
- WHEN it requests `GET /api/v1/clients`
- THEN only tenant A is returned

### Requirement: No Unauthenticated Tenant Data

`GET /api/v1/tenants/{client_id}` and `GET /api/v1/voice/signed-url` MUST
require authentication.
