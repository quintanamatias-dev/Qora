# client-secrets Specification

## Purpose

Define the behavioral contract for encrypted, per-client secret storage in the `client_secrets` table: Fernet/MultiFernet encryption keyed from an operator-managed master key, the write-only secret API, the transitional DB-then-env resolution order, master-key-absent behavior, and the degraded-status outcome when no credential resolves. This spec supersedes, for per-client CRM credentials only, the hard-startup-failure requirement in `openspec/changes/phase-b-secrets-management/specs/tenant-integration-secrets/spec.md`'s "Requirement: Startup Validation for Configured Integrations" — see the Modified Requirement section below.

---

## Requirements

### Requirement: Secrets Are Encrypted At Rest

Every value stored in `client_secrets` MUST be encrypted with `cryptography`'s `Fernet`/`MultiFernet`, keyed from the `QORA_SECRETS_MASTER_KEY` environment variable. No plaintext secret value MAY be stored in any database column, including the config JSON used by `client_integrations`.

#### Scenario: A stored secret is encrypted, not plaintext

- GIVEN a secret value is written via the secret API
- WHEN the stored row is inspected directly
- THEN the stored `ciphertext` column does not equal the plaintext value
- AND decrypting it with the configured master key recovers the original value exactly

#### Scenario: Master key rotation preserves access to previously encrypted secrets

- GIVEN a secret was encrypted when `QORA_SECRETS_MASTER_KEY` held only key A
- WHEN `QORA_SECRETS_MASTER_KEY` is updated to list a new key B first, with key A retained second
- THEN the previously stored secret still decrypts successfully
- AND a newly written secret is encrypted with key B

---

### Requirement: Secrets Are Never Exposed By Any API Response or Log

No API response, under any circumstance, MAY include a secret's ciphertext or decrypted plaintext value. Every secret-bearing API response MUST expose only the secret's name, whether it is set, and when it was last updated. No log statement MAY include a secret's ciphertext or decrypted plaintext value.

#### Scenario: Writing a secret does not echo it back

- GIVEN a secret value is submitted via `PUT /clients/{client_id}/integrations/{provider}/secret`
- WHEN the response is returned
- THEN the response body contains only `name`, `is_set`, and `updated_at`
- AND the submitted value does not appear anywhere in the response body

#### Scenario: Reading integration config never includes the secret value

- GIVEN a client has a stored secret associated with an integration
- WHEN that client's integration config is read via any GET endpoint
- THEN the response does not include the secret's ciphertext or plaintext value

#### Scenario: No log line contains a secret value

- GIVEN a secret is written, read, or resolved during a request
- WHEN the application's log output for that request is inspected
- THEN no log line contains the secret's ciphertext or decrypted plaintext value

---

### Requirement: Transitional Resolution Order — Database, Then Environment Variable

Resolving a client's CRM credential MUST attempt, in order: (1) a `client_secrets` row for that client, decrypted via the configured master key, if a master key is configured and decryption succeeds; (2) the environment variable named in the integration's configuration, matching today's `CRMConfig.resolve_api_key` behavior. If neither resolves, resolution MUST return an explicit absence, never raise an exception that propagates past the integration boundary.

#### Scenario: A database-stored secret takes precedence when available

- GIVEN a client has both a `client_secrets` row AND a legacy environment variable configured for the same credential
- AND the master key is configured and decryption succeeds
- WHEN the credential is resolved
- THEN the database-stored value is returned, not the environment variable's value

#### Scenario: Falls back to the environment variable when no database secret exists

- GIVEN a client has no `client_secrets` row for a credential
- AND the integration's configuration names an environment variable for that credential
- AND the environment variable is set to a valid, non-placeholder value
- WHEN the credential is resolved
- THEN the environment variable's value is returned

#### Scenario: Neither source resolves

- GIVEN a client has no `client_secrets` row for a credential
- AND the named environment variable is unset
- WHEN the credential is resolved
- THEN resolution returns an explicit absence
- AND no exception propagates past the integration boundary

---

### Requirement: Master Key Absence Degrades Writes, Never Silently Stores Plaintext

If `QORA_SECRETS_MASTER_KEY` is not configured, the platform MUST still start and serve requests. Any attempt to write a secret MUST be rejected with a clear error; no secret value MAY be stored unencrypted as a fallback. Secret resolution for reads MUST continue to fall back to the environment variable path unaffected.

#### Scenario: Writing a secret without a master key is rejected, not silently stored

- GIVEN `QORA_SECRETS_MASTER_KEY` is not configured
- WHEN a secret write is attempted via the secret API
- THEN the request is rejected with a clear error identifying the missing master key configuration
- AND no row is written to `client_secrets`

#### Scenario: Reads still work via the environment fallback without a master key

- GIVEN `QORA_SECRETS_MASTER_KEY` is not configured
- AND a client's credential is resolvable via its legacy environment variable
- WHEN the credential is resolved
- THEN the environment variable's value is returned successfully

#### Scenario: Platform startup is unaffected by a missing master key

- GIVEN `QORA_SECRETS_MASTER_KEY` is not configured anywhere in the deployment environment
- WHEN the application starts
- THEN startup completes successfully
- AND every client whose credentials resolve via the environment fallback operates normally

---

### Requirement: Degraded Status Instead of Startup Failure

**This requirement supersedes `phase-b-secrets-management`'s `tenant-integration-secrets` spec, "Requirement: Startup Validation for Configured Integrations," for per-client CRM credentials only.** A missing or invalid per-client CRM credential MUST NOT cause the application to exit at startup. Instead, the affected integration's status MUST be set to `degraded` with a `status_reason` identifying the missing or invalid credential, and an `ERROR`-level log line MUST be emitted naming the client and the credential. Startup MUST complete successfully regardless of how many clients have unresolvable credentials. This requirement does NOT apply to Qora-owned global credentials (`OPENAI_API_KEY`, `ELEVENLABS_API_KEY`, `QORA_API_KEY` in production), which retain their existing hard-fail startup validation, unaffected by this change.

#### Scenario: A missing per-client CRM credential does not abort startup

- GIVEN a client's CRM integration is enabled and references an environment variable that is not set, and no `client_secrets` row exists for it
- WHEN the application starts
- THEN startup completes successfully
- AND that client's integration status is `degraded` with a `status_reason` naming the missing variable
- AND an `ERROR`-level log line is emitted naming the client and the missing variable

#### Scenario: One client's degraded credential does not affect any other client

- GIVEN two clients each have an enabled CRM integration
- AND one client's credential is unresolvable while the other's resolves successfully
- WHEN the application starts
- THEN the client with the resolvable credential has `status: ok`
- AND the client with the unresolvable credential has `status: degraded`
- AND neither client's outcome is affected by the other's

#### Scenario: Qora-owned global credentials still hard-fail at startup

- GIVEN `OPENAI_API_KEY` is unset or contains a known weak placeholder
- WHEN the application starts
- THEN startup aborts, exactly as it does today
- AND this behavior is unaffected by the per-client CRM degraded-status change

#### Scenario: A weak placeholder credential is treated as unresolvable, not accepted

- GIVEN a client's CRM credential environment variable is set to a known weak placeholder value
- WHEN the credential is resolved
- THEN resolution treats it as unresolvable
- AND the integration's status becomes `degraded` with a `status_reason` identifying the placeholder, not `ok`

---

### Requirement: Secret Import From Environment Is an Explicit, Authorized Action

Copying an existing environment-variable-backed credential into encrypted database storage MUST be an explicit, superadmin-authorized API action, never an automatic side effect of a migration or a deploy.

#### Scenario: Import requires superadmin authorization

- GIVEN a non-superadmin-authenticated request
- WHEN `POST /clients/{client_id}/integrations/{provider}/secrets/import-from-env` is called
- THEN the request is rejected

#### Scenario: Import encrypts the current environment value

- GIVEN a superadmin-authenticated request
- AND the integration's configuration names an environment variable that is currently set
- AND `QORA_SECRETS_MASTER_KEY` is configured
- WHEN the import endpoint is called
- THEN a `client_secrets` row is created or updated with the environment variable's current value, encrypted
- AND subsequent credential resolution for that client returns the database-stored value, not the environment fallback

#### Scenario: Import without a master key is rejected

- GIVEN `QORA_SECRETS_MASTER_KEY` is not configured
- WHEN the import endpoint is called, even by a superadmin
- THEN the request is rejected with a clear error
- AND no row is written to `client_secrets`
