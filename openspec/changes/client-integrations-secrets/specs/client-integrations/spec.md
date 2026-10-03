# client-integrations Specification

## Purpose

Define the behavioral contract for per-client, non-secret CRM integration configuration stored in the `client_integrations` table: the schema, the `IntegrationStore` read/cache contract, the one-time `crm.yaml` import migration, the DB-backed write path (replacing filesystem writes), and the computed `status`/`status_reason` lifecycle. This spec does not define secret storage or encryption — see `specs/client-secrets/spec.md` for that contract. This spec layers on top of the existing `CRMConfig`/`CRMFieldDef`/`CustomFieldDef` Pydantic shapes (unchanged) and does not redefine their validation rules.

---

## Requirements

### Requirement: Integration Config Persists Across Deploys

A client's CRM integration configuration, once written through the API, MUST remain readable identically after a process restart against the same database, regardless of what files are present or absent in the deployed filesystem.

#### Scenario: Config survives a simulated redeploy

- GIVEN a client's CRM integration config is written via `PUT /clients/{client_id}/integrations/{provider}`
- WHEN the application process restarts against the same database (no filesystem write ever occurred for this config)
- THEN a subsequent read of that client's integration config returns the same values that were written

#### Scenario: A panel edit is never silently reverted

- GIVEN a client's CRM integration config was edited via the panel after the most recent deploy
- WHEN a new deploy occurs
- THEN the edited config is still in effect after the deploy completes
- AND no repository-tracked file overwrites the edit

---

### Requirement: One Client Integration Row Per Provider

Each client-provider pair MUST have at most one `client_integrations` row. Non-secret configuration fields (`base_id`, `table_id`, `field_mappings`, `custom_fields`, `quote_ready_fields`, status maps, `enabled`) are stored on this row; no secret value is ever stored in this table.

#### Scenario: Duplicate provider configuration is rejected

- GIVEN a client already has a `client_integrations` row for provider `airtable`
- WHEN a second row is attempted for the same client and the same provider
- THEN the write is rejected by the table's uniqueness constraint

#### Scenario: Different providers for the same client are independent

- GIVEN a client has a `client_integrations` row for provider `airtable`
- WHEN that client configures a different provider
- THEN a separate row is created, and editing one provider's config does not affect the other's

---

### Requirement: One-Time Import From Existing crm.yaml Files

A migration MUST read every existing `backend/clients/*/crm.yaml` file and create a matching `client_integrations` row containing only the non-secret fields. This migration MUST NOT read, write, or infer any `client_secrets` row.

#### Scenario: Existing crm.yaml is imported with matching non-secret fields

- GIVEN a client directory contains a valid `crm.yaml` with `base_id`, `table_id`, `field_mappings`, and `quote_ready_fields`
- WHEN the import migration runs
- THEN a `client_integrations` row is created for that client and provider
- AND its `base_id`, `table_id`, `field_mappings`, and `quote_ready_fields` match the YAML's values exactly

#### Scenario: Import migration never creates a secret row

- GIVEN a client's `crm.yaml` contains an `api_key` field, whether a literal value or an env-var name
- WHEN the import migration runs
- THEN no `client_secrets` row is created for that client as a result of this migration

#### Scenario: A client with no crm.yaml gets no row

- GIVEN a client directory has no `crm.yaml`
- WHEN the import migration runs
- THEN no `client_integrations` row is created for that client

---

### Requirement: IntegrationStore Is the Single Read Path

Every reader of per-client CRM configuration (the import service, the sync service, tool dispatch, tool registry, the voice webhook, voice context building, and the summarizer) MUST read through `IntegrationStore`, not through a direct filesystem read or a direct unmemoized database query. `IntegrationStore` MUST cache results in-process, keyed by client, and MUST invalidate a client's cached entry synchronously whenever that client's configuration is written through the API.

#### Scenario: A cached read does not query the database again

- GIVEN a client's integration config was read once via `IntegrationStore`
- AND no write has occurred for that client since, and the cache TTL has not elapsed
- WHEN the same client's config is read again
- THEN the cached value is returned without a new database query

#### Scenario: A write immediately invalidates the cache

- GIVEN a client's integration config was read and cached via `IntegrationStore`
- WHEN that client's config is updated via the write API
- THEN the next read for that client returns the updated value, not the stale cached one

#### Scenario: A missing integration returns a clear absence, not an error

- GIVEN a client has no `client_integrations` row for a given provider
- WHEN `IntegrationStore` is asked to read that client's config for that provider
- THEN it returns an explicit absence (no configuration) rather than raising an exception

---

### Requirement: Per-Client Integration Status Is Computed and Visible

Every enabled `client_integrations` row MUST have a computed `status` (`ok`, `degraded`, or `disabled`) and, when `degraded`, a human-readable `status_reason`. Status MUST be recomputed whenever the integration's configuration or associated secret changes, and at application startup.

#### Scenario: A fully configured, resolvable integration is ok

- GIVEN a client's integration is enabled and its credential resolves successfully (via the resolution order defined in `specs/client-secrets/spec.md`)
- WHEN the status is computed
- THEN `status` is `ok` and `status_reason` is empty

#### Scenario: An unresolvable credential marks the integration degraded, visibly

- GIVEN a client's integration is enabled but its credential cannot be resolved
- WHEN the status is computed
- THEN `status` is `degraded`
- AND `status_reason` names the missing or invalid credential
- AND the degraded status is retrievable via the integration status API

#### Scenario: A disabled integration is never degraded

- GIVEN a client's integration row has `enabled: false`
- WHEN the status is computed
- THEN `status` is `disabled`, regardless of whether a credential would otherwise resolve

---

### Requirement: Degraded Integration Blocks Only Its Own Tool Calls

A `degraded` integration MUST cause CRM-dependent tool calls for that client to return a clear, LLM-facing error message instead of raising an unhandled exception. A degraded integration MUST NOT affect that same client's non-CRM functionality, and MUST NOT affect any other client's functionality in any way.

#### Scenario: A degraded client's CRM tool call returns a clear error, not a crash

- GIVEN a client's CRM integration status is `degraded`
- WHEN that client's agent invokes a CRM-dependent tool during a call
- THEN the tool call returns a clear error message usable by the LLM
- AND no unhandled exception propagates out of the tool call

#### Scenario: A degraded client's non-CRM functionality is unaffected

- GIVEN a client's CRM integration status is `degraded`
- WHEN that same client's agent handles a call that does not invoke any CRM-dependent tool
- THEN the call proceeds normally with no degradation

#### Scenario: A degraded client never affects a sibling client

- GIVEN one client's CRM integration status is `degraded`
- AND a different client's CRM integration status is `ok`
- WHEN the second client's agent invokes a CRM-dependent tool
- THEN the call succeeds normally, independent of the first client's degraded status

---

### Requirement: Write API Preserves the Existing Contract, Backed by the Database

The existing `crm_config_router.py` endpoints (`GET`/`PUT .../integrations/{provider}`, `POST .../connect`, `POST .../test`, `DELETE .../disconnect`) MUST keep their existing request and response shapes, except where a shape would itself expose a secret value (see `specs/client-secrets/spec.md`). Their implementation MUST write to `client_integrations` rather than to a `crm.yaml` file.

#### Scenario: Existing panel integration continues to work unchanged

- GIVEN a panel client that calls `PUT /clients/{client_id}/integrations/{provider}` with the existing request body shape
- WHEN the request is sent after this change is deployed
- THEN the response has the same shape and status codes as before
- AND the underlying write lands in `client_integrations`, not a file

#### Scenario: Disconnecting an integration removes its row, not a file

- GIVEN a client has a `client_integrations` row for a provider
- WHEN `DELETE /clients/{client_id}/integrations/{provider}/disconnect` is called
- THEN the row is removed (or marked inactive, per the existing disconnect semantics)
- AND no filesystem operation occurs
