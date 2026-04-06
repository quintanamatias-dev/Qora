# Spec: QORA Phase 1 — Multi-client Foundation

**Change**: qora-phase1  
**Date**: 2026-04-06  
**Status**: Draft

---

## CAP-1: Per-client Prompt System

### Requirement: Filesystem Prompt Loading

`render_system_prompt()` MUST check for `backend/clients/{client_id}/prompt.md` before using the hardcoded `JAUMPABLO_PROMPT_TEMPLATE`. If the file exists, it MUST be used as the template. If not, the function MUST fall back to `JAUMPABLO_PROMPT_TEMPLATE`.

The loader MUST sanitize all variable values before injection — stripping characters that could break template boundaries or inject instructions (e.g., `{`, `}`, `\n` in single-line fields like `lead_name`).

**Supported placeholders in `prompt.md`**: `{{lead_name}}`, `{{car_make}}`, `{{car_model}}`, `{{car_year}}`, `{{current_insurance}}`, `{{broker_name}}`, `{{agent_name}}`.

#### Scenario: Client with prompt.md file

- GIVEN a client `demo-inmobiliaria` with `backend/clients/demo-inmobiliaria/prompt.md` on disk
- WHEN `render_system_prompt(client, lead)` is called
- THEN the rendered prompt uses the content of `prompt.md` with variables substituted
- AND the `JAUMPABLO_PROMPT_TEMPLATE` is NOT used

#### Scenario: Client without prompt.md (fallback)

- GIVEN a client `quintana-seguros` with NO `prompt.md` file on disk
- WHEN `render_system_prompt(client, lead)` is called
- THEN the rendered prompt uses `JAUMPABLO_PROMPT_TEMPLATE`
- AND no file I/O error is raised

#### Scenario: Prompt injection attempt in lead_name

- GIVEN a lead whose `name` contains `}}{{agent_name}}`
- WHEN `render_system_prompt(client, lead)` is called
- THEN the rendered prompt treats the name as a literal string
- AND no unintended variable substitution occurs

---

## CAP-2: Knowledge Base

### Requirement: Knowledge Injection into System Prompt

`render_system_prompt()` MUST check for `backend/clients/{client_id}/knowledge.md`. If it exists, its contents MUST be appended to the rendered system prompt under the heading `## INFORMACIÓN DE LA EMPRESA`. The injected block MUST be truncated to a maximum of 2000 tokens before appending. If the file does not exist, no knowledge section is added.

#### Scenario: Client with knowledge.md

- GIVEN `backend/clients/quintana-seguros/knowledge.md` exists with 800 tokens of content
- WHEN `render_system_prompt(client, lead)` is called
- THEN the returned string ends with `## INFORMACIÓN DE LA EMPRESA\n{content}`

#### Scenario: knowledge.md exceeds 2000 tokens

- GIVEN `knowledge.md` contains 3000 tokens of content
- WHEN `render_system_prompt(client, lead)` is called
- THEN the injected content is truncated to ≤ 2000 tokens
- AND a warning is logged indicating truncation occurred

#### Scenario: Client without knowledge.md

- GIVEN `backend/clients/demo-inmobiliaria/knowledge.md` does NOT exist
- WHEN `render_system_prompt(client, lead)` is called
- THEN the returned string does NOT contain `## INFORMACIÓN DE LA EMPRESA`

---

## CAP-3: Client CRUD API

### Requirement: POST /api/v1/clients — Create Client

`POST /api/v1/clients` MUST create a new client record in the DB. The `client_id` MUST be validated as a slug: lowercase letters, digits, and hyphens only (`^[a-z0-9-]+$`). If validation fails, the endpoint MUST return HTTP 422. If a client with the same `id` already exists, it MUST return HTTP 409.

#### Scenario: Successful creation

- GIVEN a valid payload `{ "id": "new-broker", "name": "New Broker", "broker_name": "NB", "agent_name": "Ana", "voice_id": "abc123" }`
- WHEN `POST /api/v1/clients` is called
- THEN HTTP 201 is returned with the created client object
- AND the client is retrievable via `GET /api/v1/clients/new-broker`

#### Scenario: Invalid slug

- GIVEN payload with `"id": "New Broker!"` (uppercase and special chars)
- WHEN `POST /api/v1/clients` is called
- THEN HTTP 422 is returned with a validation error on `id`

#### Scenario: Duplicate client_id

- GIVEN `quintana-seguros` already exists in the DB
- WHEN `POST /api/v1/clients` with `"id": "quintana-seguros"` is called
- THEN HTTP 409 is returned

### Requirement: GET /api/v1/clients — List Active Clients

`GET /api/v1/clients` MUST return only clients where `is_active = true`, as a JSON array.

#### Scenario: Lists only active clients

- GIVEN two active clients and one soft-deleted client
- WHEN `GET /api/v1/clients` is called
- THEN the response contains exactly the two active clients
- AND the soft-deleted client is NOT in the list

### Requirement: GET /api/v1/clients/{client_id} — Get Single Client

#### Scenario: Client found

- GIVEN `quintana-seguros` exists and `is_active = true`
- WHEN `GET /api/v1/clients/quintana-seguros` is called
- THEN HTTP 200 is returned with the client object

#### Scenario: Client not found

- GIVEN `unknown-client` does NOT exist in the DB
- WHEN `GET /api/v1/clients/unknown-client` is called
- THEN HTTP 404 is returned

### Requirement: PATCH /api/v1/clients/{client_id} — Update Client

`PATCH /api/v1/clients/{client_id}` MUST accept partial updates. Only provided fields are updated. `id` MUST NOT be updatable via PATCH.

#### Scenario: Successful partial update

- GIVEN `quintana-seguros` exists
- WHEN `PATCH /api/v1/clients/quintana-seguros` with `{ "agent_name": "JuanPablo" }` is called
- THEN HTTP 200 is returned with the updated client
- AND only `agent_name` changed; other fields are unchanged

### Requirement: DELETE /api/v1/clients/{client_id} — Soft Delete

`DELETE /api/v1/clients/{client_id}` MUST set `is_active = false`. It MUST NOT remove the DB record.

#### Scenario: Soft delete

- GIVEN `demo-inmobiliaria` exists with `is_active = true`
- WHEN `DELETE /api/v1/clients/demo-inmobiliaria` is called
- THEN HTTP 200 is returned
- AND `GET /api/v1/clients` does NOT include `demo-inmobiliaria`
- AND the DB record still exists with `is_active = false`

---

## CAP-4: Client Onboarding CLI

### Requirement: create-client Command

`python -m backend.cli create-client --id X --broker-name Y --agent-name Z` MUST:
1. Insert a `Client` record into the DB (if not already present).
2. Create `backend/clients/{id}/` directory.
3. Write `backend/clients/{id}/prompt.md` with a template containing all supported `{{variables}}`.
4. Write `backend/clients/{id}/knowledge.md` with placeholder content.

The command MUST be idempotent: if `prompt.md` already exists, it MUST NOT overwrite it. If the DB record already exists, it MUST NOT fail — it MUST log that the client already exists and continue with directory/file creation steps.

#### Scenario: Fresh client creation

- GIVEN `demo-inmobiliaria` does NOT exist in DB or filesystem
- WHEN `python -m backend.cli create-client --id demo-inmobiliaria --broker-name "Propiedades BA" --agent-name "Sofía"`
- THEN DB record is created with `is_active = true`
- AND `backend/clients/demo-inmobiliaria/prompt.md` exists with `{{lead_name}}`, `{{broker_name}}`, `{{agent_name}}` placeholders
- AND `backend/clients/demo-inmobiliaria/knowledge.md` exists

#### Scenario: Idempotent re-run (prompt.md already customized)

- GIVEN `demo-inmobiliaria` already has a customized `prompt.md`
- WHEN the `create-client` command is run again with the same `--id`
- THEN `prompt.md` is NOT overwritten
- AND the command exits with a success code (0)

#### Scenario: Invalid slug

- GIVEN `--id "Bad Client!"` is provided
- WHEN the command runs
- THEN it exits with a non-zero code and prints a validation error

---

## CAP-5: Web Demo Client Selector

### Requirement: Client Dropdown in Web Demo

The web demo (`backend/app/static/index.html`) MUST include a `<select>` dropdown populated from `GET /api/v1/clients`. Only active clients are shown. Selecting a client MUST trigger a reload of the lead dropdown via `GET /api/v1/leads?client_id={id}`. The selected `client_id` MUST be included in the `dynamic_variables` sent to ElevenLabs when the call is initiated.

#### Scenario: Dropdown populates on page load

- GIVEN two active clients exist (`quintana-seguros`, `demo-inmobiliaria`)
- WHEN the web demo page loads
- THEN both appear as options in the client dropdown

#### Scenario: Lead dropdown updates on client selection

- GIVEN `demo-inmobiliaria` is selected in the client dropdown
- WHEN the selection changes
- THEN `GET /api/v1/leads?client_id=demo-inmobiliaria` is called
- AND the lead dropdown is repopulated with the results

#### Scenario: client_id sent to ElevenLabs

- GIVEN `demo-inmobiliaria` is the selected client and a lead is selected
- WHEN the user starts a call
- THEN `dynamic_variables` includes `{ "client_id": "demo-inmobiliaria" }`

---

## CAP-6: Client Routing (MODIFIED — removes default fallback)

### Requirement: Strict client_id Resolution in Webhook

**Previously**: If `client_id` was missing or unresolvable, `default_client_id` from settings was used as a silent fallback.

The webhook (`/api/v1/voice/custom-llm`) MUST resolve `client_id` from: `elevenlabs_extra_body.client_id` → top-level field → `model_extra`. If `client_id` is absent after all sources are exhausted, the endpoint MUST return HTTP 422. If `client_id` is present but not found in DB, the endpoint MUST return HTTP 404. The `default_client_id` setting and fallback MUST be removed.

The ElevenLabs initiation webhook URL MUST include `?client_id={client_id}` as a query parameter. The web demo MUST always send `client_id` in `dynamic_variables`.

#### Scenario: client_id resolves to valid client

- GIVEN `client_id = "quintana-seguros"` is in `elevenlabs_extra_body`
- WHEN the webhook is called
- THEN the request proceeds normally with that client's config

#### Scenario: client_id absent — 422

- GIVEN no `client_id` is present in any field of the request
- WHEN `/api/v1/voice/custom-llm` is called
- THEN HTTP 422 is returned

#### Scenario: client_id not found in DB — 404

- GIVEN `client_id = "ghost-client"` is sent but does not exist in DB
- WHEN the webhook is called
- THEN HTTP 404 is returned with `{"error": "client not found"}`

#### Scenario: Initiation webhook — client_id missing — 422

- GIVEN no `client_id` query param or body field
- WHEN `POST /api/v1/voice/initiation` is called
- THEN HTTP 422 is returned (current behavior already enforces this — no change needed)

---

## CAP-7: Second Pilot Client — demo-inmobiliaria

### Requirement: demo-inmobiliaria Client Fixture

A second client `demo-inmobiliaria` MUST be creatable via the CLI and seeded with at least 3 test leads representing property inquiries. The client MUST use a distinct `broker_name`, `agent_name`, and `prompt.md` style (real estate, not insurance). The prompt MUST use the same `{{variable}}` format.

This client MUST be independently selectable in the web demo and MUST produce a distinct system prompt when a call is initiated.

#### Scenario: demo-inmobiliaria produces different prompt than quintana-seguros

- GIVEN both clients exist with their respective `prompt.md` files
- WHEN `render_system_prompt` is called for each with the same lead
- THEN the two returned strings are different
- AND `demo-inmobiliaria` prompt does NOT reference insurance terminology

#### Scenario: 3 test leads for demo-inmobiliaria

- GIVEN `demo-inmobiliaria` is seeded with test data
- WHEN `GET /api/v1/leads?client_id=demo-inmobiliaria` is called
- THEN at least 3 leads are returned with property-relevant data (e.g., `car_make` field repurposed or notes describing a property)

#### Scenario: End-to-end multi-tenancy

- GIVEN `quintana-seguros` and `demo-inmobiliaria` both exist
- WHEN the web demo switches from one to the other and a call is initiated
- THEN the system prompt changes to match the selected client
- AND no cross-client data leaks between the two calls
