# Proposal: Qora Config Phase 3 — Client Integrations & Secrets

## Intent

Today, per-client CRM configuration lives entirely in `backend/clients/{client}/crm.yaml`, a file checked into the repository and rewritten in place by `crm_config_router.py` (`PUT .../integrations/{provider}`, `POST .../connect`, `PUT .../mappings`, `DELETE .../disconnect`) whenever the panel edits it. The survey's own critical finding #3 is that this file is **lost on every deploy** — the server-side working copy is discarded and replaced by the repo's checked-in version on the next deploy, silently reverting any panel edit, including the API key when one is stored as a literal value instead of an env-var name. Critical finding #4 compounds this: `validate_all_integration_credentials` (`core/credentials.py`) calls `sys.exit` at startup if ANY client's configured CRM env var is missing or a weak placeholder — one misconfigured client's CRM integration takes down the entire platform, every client, at boot.

The roadmap's phase 3 goal is explicit: "CRM and API keys per client in the DB, encrypted. A misconfigured client must not bring down the others." This change moves CRM integration configuration and API keys out of the filesystem and into two new tables — `client_integrations` (non-secret config, replacing `crm.yaml`) and `client_secrets` (encrypted credentials, replacing per-client env vars) — and replaces the sys.exit boot gate with a per-client degraded status that never blocks unrelated clients or unrelated calls for the same client.

## Scope

### In Scope

- `client_integrations` table: one row per `(client_id, provider)`, storing the non-secret CRM config (`base_id`, `table_id`, `field_mappings`, `custom_fields`, `quote_ready_fields`, status maps, `enabled`) plus a computed `status` (`ok` | `degraded` | `disabled`), `status_reason`, and `last_checked_at`. Mutable for now (rare edits), not revisioned — see D1.
- `client_secrets` table: one row per `(client_id, name)`, storing a Fernet-encrypted ciphertext, a `key_id` identifying which master key encrypted it, and audit columns (`created_by`/`updated_by`/`at`). Never revisioned; mutable; audited via columns + structured logs, not a history table — see D1.
- Encryption module using `cryptography`'s `MultiFernet`, keyed from `QORA_SECRETS_MASTER_KEY` (comma-separated key list, first key encrypts, all keys attempt decrypt — supports rotation). New dependency added to `backend/pyproject.toml`.
- `IntegrationStore`: the single read path for CRM config, backed by the DB with an in-process, per-client cache (invalidated synchronously on every write through the API, bounded by a short TTL as a safety net) so the hot path (per-turn CRM reads in `voice/webhook.py`) does not hit the DB on every turn.
- Transitional secret-resolution order for a client's CRM API key: DB secret (if a master key is configured and decryption succeeds) → legacy env var named in the integration config (today's behavior, unchanged fallback) → missing → integration marked `degraded`, never a platform crash.
- Boot behavior change: no `sys.exit` for any per-client integration problem. Startup computes and persists each configured integration's status; a degraded client's CRM tool calls return a clear tool-error to the LLM instead of raising; every other call (non-CRM for that client, everything for every other client) is unaffected. Platform-level required secrets (`OPENAI_API_KEY`, `ELEVENLABS_API_KEY`, `QORA_API_KEY` in production) keep their existing hard-fail — this change narrows the blast radius of CRM-specific failures only, it does not relax platform-credential validation.
- One-time import migration: for each `backend/clients/*/crm.yaml`, create the corresponding `client_integrations` row (non-secret fields only). Secrets are explicitly NOT imported by the migration (the master key may not exist yet at migrate time); a separate admin endpoint `POST /clients/{id}/integrations/{provider}/secrets/import-from-env` copies the named env var's current value into `client_secrets`, encrypted, once an operator configures the master key.
- Router cutover: `crm_config_router.py` keeps its existing route shape and response contract where possible, but every write goes to the DB instead of rewriting `crm.yaml`; a write-only secret endpoint and a read-only integration-status endpoint are added.
- Dedupe the ALL_CAPS env-var-name regex (`^[A-Z][A-Z0-9_]+$`), currently duplicated in `crm_config.py`, `credentials.py`, and `crm_config_router.py`, into one shared helper.
- Final cutover task: once the DB is the sole source of truth, remove `crm.yaml` read paths from every consumer and delete the files from the repo.

### Out of Scope

- Revision history / rollback for `client_integrations` or `client_secrets` — both are mutable for now, audited by columns and logs only; a revisioned model (mirroring `agent_config_revisions`) is an explicit future phase, not this one (D1).
- Secret types other than CRM API keys (no OAuth token refresh, no multi-field credential bundles) — `client_secrets` is a flat `name → ciphertext` store; structured multi-secret integrations are a future extension of the same table, not a new shape in this phase.
- Automatic secret rotation — `MultiFernet` supports decrypting with an old key while encrypting with a new one, but triggering re-encryption of existing rows on rotation is an operational runbook step (phase 7 rollout notes), not an automated background job in this phase.
- CRM providers beyond Airtable — the config shape already supports a `provider` discriminator; adding HubSpot or others is unaffected by this change and remains future work.
- The three-level config inheritance model (Qora standard → Client → Agent) from phase 1b (`agent-config-inheritance`) — CRM/secrets are a parallel, independent config surface; this phase does not fold CRM fields into that resolver.
- Any change to `docs/` or `backend/alembic` history outside this change's own new migration files — other concurrent work owns those surfaces.

## Capabilities

> This section is the CONTRACT between proposal and specs phases.

### New Capabilities

- `client-integrations`: the `client_integrations` table, its computed `status`/`status_reason` lifecycle, the `IntegrationStore` read/cache contract, the one-time crm.yaml import migration, and the router write path that persists to the DB instead of the filesystem.
- `client-secrets`: the `client_secrets` table, Fernet/MultiFernet encryption with `QORA_SECRETS_MASTER_KEY`, the write-only secret API (name + is_set + updated_at only, never ciphertext or plaintext in any response or log), the transitional DB-then-env resolution order, and the master-key-absent degraded-write behavior (503 on secret write, resolution still falls back to env).

### Modified Capabilities

- `tenant-integration-secrets` (phase-b-secrets-management): the requirement "A missing credential for a configured, active integration MUST cause a hard startup failure" is **superseded** for CRM/per-client integration credentials specifically. Phase 3 replaces this with a per-client degraded status that never blocks startup or other clients — see design.md's modified-requirement entry and rationale (survey critical #4). Qora-owned global credentials (`OPENAI_API_KEY`, `ELEVENLABS_API_KEY`) are unaffected and keep their existing hard-fail behavior; this modification is scoped to per-client CRM credentials only.

## Approach

**Crypto and schema first, then the read path, then every reader, then the write path, then boot behavior, then cleanup, then rollout** — each layer additive until the reader-cutover task, matching the staged-rollout precedent already used in phase 1a/1b.

1. Encryption module (`MultiFernet`, settings, `cryptography` dependency) — pure, nothing calls it yet
2. Schema (`client_integrations`, `client_secrets`) + one-time crm.yaml import migration — additive
3. `IntegrationStore` + cache + secret-resolution order — additive, nothing calls it yet
4. Cut over every reader (`crm_import_service.py`, `crm_sync_service.py`, `tools/dispatcher.py`, `tools/registry.py`, `voice/webhook.py`, `voice/context.py`, `summarizer.py`) to `IntegrationStore` instead of `CRMConfigLoader`
5. Router writes to the DB instead of `crm.yaml`; add secret write/import endpoints and the integration-status endpoint
6. Boot validation computes per-client status instead of `sys.exit`; CRM tool calls for a degraded client return a tool error instead of raising
7. Remove `crm.yaml` read paths and delete the files; dedupe the ALL_CAPS regex into one shared helper
8. Prod rollout: set `QORA_SECRETS_MASTER_KEY` in Railway, import the one real secret (quintana-seguros Airtable key) from env, verify

## Affected Areas

| Area | Impact | Description |
|------|--------|--------------|
| `backend/app/core/crypto.py` (new) | New | `MultiFernet`-backed encrypt/decrypt helpers, keyed from `QORA_SECRETS_MASTER_KEY` |
| `backend/app/core/config.py` | Modified | `Settings.qora_secrets_master_key: str \| None` (comma-separated key list) |
| `backend/pyproject.toml` | Modified | Add `cryptography` dependency |
| `backend/app/tenants/models.py` | Modified | New `ClientIntegration`, `ClientSecret` models |
| `backend/alembic/versions/20261003_0021_client_integrations_secrets_schema.py` (new) | New | `CREATE TABLE client_integrations`, `CREATE TABLE client_secrets` |
| `backend/alembic/versions/20261003_0022_import_crm_yaml_integrations.py` (new) | New | One-time import: `backend/clients/*/crm.yaml` → `client_integrations` rows (non-secret fields only) |
| `backend/app/integrations/integration_store.py` (new) | New | `IntegrationStore` — DB-backed read, in-process per-client cache, write-through invalidation, secret resolution order |
| `backend/app/integrations/crm_config.py` | Modified | `CRMConfigLoader` superseded by `IntegrationStore`; `CRMConfig`/`CRMFieldDef`/`CustomFieldDef` Pydantic shapes retained and reused as the `IntegrationStore` return type |
| `backend/app/integrations/crm_config_router.py` | Modified | Writes go to the DB via `IntegrationStore`/service functions, not `yaml.dump`; new secret write-only + import-from-env + status endpoints |
| `backend/app/integrations/crm_import_service.py` | Modified | Reads via `IntegrationStore` (lines 171, 189 today) |
| `backend/app/integrations/crm_sync_service.py` | Modified | Reads via `IntegrationStore` (lines 69, 83 today) |
| `backend/app/tools/dispatcher.py` | Modified | Reads via `IntegrationStore` (lines 42, 135, 188 today); degraded-client CRM tool calls return a tool error |
| `backend/app/tools/registry.py` | Modified | Reads via `IntegrationStore` (line 154 today) |
| `backend/app/voice/webhook.py` | Modified | Hot-path per-turn CRM reads (lines ~1012, 1104, 1147, 1225) go through `IntegrationStore`'s cache, not a filesystem read per turn |
| `backend/app/voice/context.py` | Modified | Lines 404–411 read via `IntegrationStore` |
| `backend/app/summarizer.py` | Modified | Line 1172 reads via `IntegrationStore` |
| `backend/app/core/credentials.py` | Modified | `validate_all_integration_credentials` no longer calls `sys.exit`; computes and persists per-client integration status instead; shared ALL_CAPS regex helper moved here, imported by `crm_config.py` and `crm_config_router.py` |
| `backend/app/main.py` | Modified | Startup calls the renamed/refactored boot validator; no behavior change to the call site itself beyond no longer aborting the process |
| `backend/clients/*/crm.yaml` | Deleted (final task) | Removed once the DB is the sole source of truth and no reader touches the filesystem path |

## Safety Model

1. **One client's misconfiguration never affects another client, or the platform** — the core guarantee this phase exists to deliver (survey critical #4). No per-client integration state can call `sys.exit`; the only hard-fail paths left at boot are the pre-existing Qora-owned global credentials, which are out of scope for this change.
2. **Secrets are never returned by any API, and never logged** — every secret-bearing endpoint response and every log statement is reviewed to confirm only `name`, `is_set`, and `updated_at` are ever exposed; the ciphertext and the decrypted plaintext never leave the encryption boundary.
3. **Config edits survive every deploy** — the entire reason `client_integrations`/`client_secrets` exist in the DB instead of the filesystem is that a deploy no longer discards a panel edit (survey critical #3); this is verified by an explicit test that simulates a redeploy (process restart against the same DB) and asserts the edited config is still present.
4. **Fail visibly, not silently, when the master key is absent** — if `QORA_SECRETS_MASTER_KEY` is unset, secret writes return 503 with a clear message rather than silently storing plaintext or dropping the write; reads still work via the env-var fallback so existing clients are unaffected.
5. **Transitional fallback, not a permanent dual system** — the DB-then-env resolution order (D3) exists only to make the cutover safe for the one real client (quintana-seguros) that has a live env-var-backed secret today; task 8 explicitly imports that one secret and the env fallback has no new clients added to it going forward.

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|-------------|
| `IntegrationStore`'s cache serves stale config after a write made outside the API (e.g. a direct DB edit) | Low | Cache has both write-through invalidation (primary mechanism) AND a short TTL (safety net); documented as "cache coherence is API-write-driven, not DB-change-driven" — any out-of-band DB write is an operational anti-pattern, not a supported path |
| Master key rotation (`MultiFernet`) is misconfigured (new key first in the list before any row is re-encrypted) | Med | `MultiFernet` decrypts with ANY key in the list, encrypts with the first — rotation runbook (task 8) requires re-encrypting existing rows with the new key as first before removing the old key from the list; documented explicitly, not assumed safe by default |
| Removing `crm.yaml` (final task) breaks a reader this survey's grep missed | Med | Task 7 only runs after every known reader (enumerated above, confirmed via `grep` against `CRMConfigLoader`/`crm_config` imports) is cut over and the full backend suite passes; the task's RED test asserts no remaining import of `CRMConfigLoader` exists in `backend/app/` before deletion |
| A client's CRM integration was relying on the hard startup failure as an (accidental) data-quality gate | Low | `status: degraded` with `status_reason` is surfaced in the admin API and logged at `ERROR` level at boot — visibility is preserved, only the platform-wide crash is removed |
| Env-var fallback (D3) papers over a forgotten secret import indefinitely | Low | Task 8's rollout explicitly imports the one real secret; the fallback path is logged at `WARNING` when used so an unmigrated client is visible in logs, not silently working forever |

## Rollback Plan

- **Crypto module + dependency (task 1)**: pure addition, nothing calls it yet; revert the PR, remove the dependency line.
- **Schema + import migration (task 2)**: `alembic downgrade -1` (twice, for both new revisions) drops `client_integrations` and `client_secrets`; no runtime code depends on them yet.
- **IntegrationStore (task 3)**: pure addition, nothing calls it yet; revert the PR.
- **Reader cutover (task 4)**: revert the PR; every reader reverts to `CRMConfigLoader` reading `crm.yaml`, which is untouched and still present on disk until task 7.
- **Router write cutover (task 5)**: revert the PR; `crm_config_router.py` reverts to writing `crm.yaml` directly.
- **Boot validation change (task 6)**: revert the PR; `validate_all_integration_credentials` reverts to its `sys.exit` behavior — explicitly a regression of this phase's own goal, acceptable only as an emergency rollback, not a target state.
- **crm.yaml removal + regex dedupe (task 7)**: files are removed from the repo, not from a running deploy's filesystem; reverting the PR restores them from git history. This task only runs after task 4–6 are proven stable, so rollback here is low-risk by construction.
- **Prod rollout (task 8)**: additive-only up to this point; rollback is unsetting `QORA_SECRETS_MASTER_KEY` (resolution falls back to env, matching pre-phase-3 behavior) and re-running task 6's revert if the degraded-status behavior itself is the problem.

## Dependencies

- Depends on `backend/alembic`'s current head, `20261003_0020_delete_qora_demo_tenant.py`; this change's migrations are chained starting at `20261003_0021`.
- New third-party dependency: `cryptography` (for `Fernet`/`MultiFernet`).
- Independent of `agent-config-inheritance` (phase 1b) — no shared tables, no shared resolver; both phases may land in either order.
- `openspec/changes/phase-b-secrets-management/specs/tenant-integration-secrets/spec.md`'s hard-startup-failure requirement is explicitly superseded for CRM credentials by this change (see Modified Capabilities); that spec's other requirements (global Qora credential validation, the centralized ALL_CAPS resolver pattern, the "CRM is optional per client" requirement) are reused unchanged, not rewritten.

## Review / Deployment Strategy

Eight task groups, each sized to review within a single PR (~≤400 changed lines target): (1) crypto module + settings + dependency, (2) schema + import migration, (3) `IntegrationStore` + cache + key resolution, (4) cut over all readers, (5) router writes to DB + secret endpoints, (6) boot validation → degraded status, (7) remove `crm.yaml` files + dedupe the env-name regex, (8) prod rollout notes. See tasks.md for the full forecast and per-task RED/GREEN/rollback detail.

## Success Criteria

- [ ] `client_integrations` and `client_secrets` tables exist; the one-time import migration creates a `client_integrations` row for every existing `backend/clients/*/crm.yaml` with matching non-secret fields
- [ ] No secret value (ciphertext or plaintext) is ever returned by any API response or written to any log line — verified by an explicit test asserting the response schema and a log-capture test
- [ ] A client with a missing or invalid CRM secret does NOT prevent the platform from starting, and does NOT affect any other client's calls or that same client's non-CRM calls
- [ ] A panel edit to CRM config or a CRM secret survives a process restart against the same DB (simulated redeploy)
- [ ] Every reader enumerated in Affected Areas reads via `IntegrationStore`, not `CRMConfigLoader`/`crm.yaml`, by the end of task 4
- [ ] `crm.yaml` files are deleted from the repo and no code path reads them, by the end of task 7
- [ ] The ALL_CAPS env-var-name regex exists in exactly one place, imported by every consumer that previously duplicated it
- [ ] Full backend test suite passes before closing the change

## Next Recommended Phase

**sdd-tasks** → the eight-task breakdown in `tasks.md`. See `specs/client-integrations/spec.md` and `specs/client-secrets/spec.md` for the behavioral contracts.
