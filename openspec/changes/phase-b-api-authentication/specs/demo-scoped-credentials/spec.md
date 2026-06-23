# Demo Scoped Credentials Specification

## Purpose

The `/demo` surface is public and must remain easy to use for full voice pipeline QA. Server-side resolution of demo client/agent identity from env-configured IDs eliminates the need to expose any API key or admin credential to the browser. Demo sessions carry full pipeline write permissions bounded to the configured client/agent/lead/session scope.

## Requirements

### Requirement: Server-Side Demo Context Resolution

A dedicated auth-exempt endpoint (`/api/v1/demo/context`) MUST resolve the demo agent context server-side using `QORA_DEMO_CLIENT_ID` and `QORA_DEMO_AGENT_ID` env vars. The response MUST contain only demo-safe data: `elevenlabs_agent_id`, `client_name`, `agent_name`. No API key, webhook secret, or admin-level data MUST appear in the response or in browser network traffic.

#### Scenario: Demo context endpoint returns safe metadata

- GIVEN `QORA_DEMO_CLIENT_ID` and `QORA_DEMO_AGENT_ID` are configured and point to valid DB records
- WHEN `GET /api/v1/demo/context` is called (no auth header required)
- THEN the response contains `{ elevenlabs_agent_id, client_name, agent_name }` and nothing else

#### Scenario: No credential leakage in demo context response

- GIVEN a demo context request
- WHEN the response is inspected
- THEN `QORA_API_KEY`, `QORA_WEBHOOK_SECRET`, and any other secret value are absent from the response body and headers

#### Scenario: Missing demo env vars

- GIVEN `QORA_DEMO_CLIENT_ID` or `QORA_DEMO_AGENT_ID` is not configured
- WHEN `GET /api/v1/demo/context` is called
- THEN the system returns HTTP 503 with a configuration error message; no partial or malformed context is returned

### Requirement: Demo Session Full Pipeline Writes

Demo calls MUST establish a full `AuthorizedSession` at session start using the same mechanism as production calls. The demo `AuthorizedSession` MUST carry write permissions for all standard voice pipeline operations: call session creation, transcript write, captured data write, and post-call analysis. This enables `/demo` to QA the complete Qora pipeline.

#### Scenario: Demo session enables full pipeline write

- GIVEN a demo session with a valid `AuthorizedSession` scoped to the configured demo client/agent/lead
- WHEN the voice conversation completes
- THEN transcript, call session, captured data, and post-call analysis records are all written successfully

### Requirement: Demo Write Boundary Enforcement

Demo writes MUST be strictly bounded to the configured demo `client_id`, `agent_id`, `lead_id`, and `session_id`. Admin writes, global config mutations, and access to data belonging to any other client MUST be blocked at the scope-validation layer.

#### Scenario: Demo session blocked from cross-tenant write

- GIVEN an active demo `AuthorizedSession` scoped to demo `client_id=X`
- WHEN the session attempts to write to data belonging to `client_id=Y`
- THEN the system returns HTTP 403; no data for `client_id=Y` is written

#### Scenario: Demo session blocked from admin write

- GIVEN an active demo `AuthorizedSession`
- WHEN the session attempts an admin-level operation (e.g., creating a new Client record)
- THEN the system returns HTTP 403; the operation does not execute

### Requirement: Admin Key Never Exposed to Demo

`QORA_API_KEY` MUST NOT be returned by any demo endpoint, injected into any static file served by `/demo`, or transmitted to the browser in any form. The `/demo` static file mount is public; no server-rendered key injection is permitted.

#### Scenario: Static demo files contain no secrets

- GIVEN the `/demo` static files are served
- WHEN their contents are inspected
- THEN no instance of `QORA_API_KEY` or `QORA_WEBHOOK_SECRET` appears in any file
