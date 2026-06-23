# Tenant Integration Secrets Specification

## Purpose

Defines how per-client integration credentials (Airtable now; HubSpot and others in the future) are validated and resolved at startup. These are NOT Qora-owned provider credentials — they are optional, client-specific secrets tied to third-party CRM or data integrations. A client without a CRM integration has no such secrets. A client with a CRM integration MUST have all referenced secrets present and valid before the application serves requests.

## Boundary

| Secret Type | Owner | Scope | Managed By |
|---|---|---|---|
| `OPENAI_API_KEY`, `ELEVENLABS_API_KEY`, future LLM provider keys | Qora | Global | `Settings` — see `secrets-validation` spec |
| `{CLIENT}_AIRTABLE_API_KEY`, future `{CLIENT}_HUBSPOT_API_KEY`, etc. | Qora (per-client cost) | Per-client integration | This spec |

> Qora owns all API credentials including per-client integration keys. "Per-client" here refers to configuration scope, not credential ownership.

## Requirements

### Requirement: CRM Integration Is Optional Per Client

A client configuration MUST NOT require a CRM credential unless `crm.yaml` exists for that client and the integration is explicitly configured.

If a client has no `crm.yaml`, no CRM credential validation is performed for that client.

#### Scenario: Client with no crm.yaml

- GIVEN a client directory exists at `backend/clients/{client-id}/`
- AND no `crm.yaml` is present in that directory
- WHEN the application starts
- THEN no CRM credential error is raised for that client
- AND the client operates without CRM integration

#### Scenario: Client with crm.yaml but integration disabled

- GIVEN `crm.yaml` exists but the integration is marked as disabled or inactive
- WHEN the application starts
- THEN no credential validation is performed for that integration

---

### Requirement: Startup Validation for Configured Integrations

If a `crm.yaml` references an env var name as a credential, the system MUST validate that the env var is set and non-empty at startup, before serving requests.

A missing credential for a configured, active integration MUST cause a hard startup failure with a clear error naming the client and the missing variable.

#### Scenario: Airtable credential present for active integration

- GIVEN `backend/clients/quintana/crm.yaml` references `QUINTANA_AIRTABLE_API_KEY`
- AND the integration is active
- AND `QUINTANA_AIRTABLE_API_KEY` is set to a valid non-empty value
- WHEN the application starts
- THEN startup succeeds

#### Scenario: Airtable credential missing for active integration

- GIVEN `backend/clients/quintana/crm.yaml` references `QUINTANA_AIRTABLE_API_KEY`
- AND the integration is active
- AND `QUINTANA_AIRTABLE_API_KEY` is not set
- WHEN the application starts
- THEN startup aborts
- AND the error names `QUINTANA_AIRTABLE_API_KEY` and the client `quintana`

#### Scenario: CRM credential is a known placeholder

- GIVEN `QUINTANA_AIRTABLE_API_KEY` is set to `change-me-before-production`
- AND the integration is active
- WHEN the application starts
- THEN startup aborts with a placeholder error for that variable

---

### Requirement: Centralized Credential Resolver

The system MUST resolve per-client CRM credentials through a single centralized function, not through scattered `os.environ.get()` calls in integration code.

The resolver MUST treat ALL_CAPS values in `crm.yaml` as env var references and look them up from the validated environment. Non-ALL_CAPS values MUST be treated as literal (dev/test only) and SHOULD emit a warning in non-local environments.

#### Scenario: Env var reference resolved correctly

- GIVEN `crm.yaml` contains `api_key: QUINTANA_AIRTABLE_API_KEY`
- AND `QUINTANA_AIRTABLE_API_KEY` is set to a valid value
- WHEN the credential resolver is called for the Airtable integration
- THEN the resolver returns the value of `QUINTANA_AIRTABLE_API_KEY`
- AND no `os.environ.get()` call exists outside the resolver

#### Scenario: Literal value in crm.yaml (dev/test)

- GIVEN `crm.yaml` contains `api_key: mytestapikey123` (not ALL_CAPS)
- WHEN the credential resolver is called
- THEN the resolver returns `mytestapikey123` as a literal value
- AND a warning is emitted if the environment is not local dev

#### Scenario: Resolver called for missing env var reference

- GIVEN `crm.yaml` contains `api_key: QUINTANA_AIRTABLE_API_KEY`
- AND `QUINTANA_AIRTABLE_API_KEY` is not in the environment
- WHEN the credential resolver is called
- THEN the resolver raises a clear error naming the missing variable
- AND does not return `None` silently

---

### Requirement: Qora Provider Credentials Are Not Per-Client Secrets

The system MUST NOT require or accept per-client overrides of global Qora-owned credentials (`OPENAI_API_KEY`, `ELEVENLABS_API_KEY`, and future LLM provider keys) via `crm.yaml` or any per-client config file.

Model or provider routing for a client MAY be configured via agent-level settings (future phase), but credential ownership remains with Qora.

#### Scenario: crm.yaml does not reference global provider credentials

- GIVEN any `crm.yaml` for any client
- WHEN the startup CRM validation runs
- THEN global Qora credential variables (`OPENAI_API_KEY`, `ELEVENLABS_API_KEY`) are NOT looked up or validated by the CRM validator
- AND those credentials are exclusively managed by `Settings`
