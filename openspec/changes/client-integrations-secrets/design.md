# Design: Qora Config Phase 3 — Client Integrations & Secrets

## Technical Approach

Replace the filesystem-backed `backend/clients/{client}/crm.yaml` with two DB tables — `client_integrations` (non-secret config) and `client_secrets` (encrypted credentials) — read through a single caching store (`IntegrationStore`) so the per-turn voice hot path keeps its current latency profile. Encryption uses `cryptography`'s `MultiFernet`, keyed from an operator-managed env var, with a transitional DB-then-env resolution order so the one real client with a live secret today (quintana-seguros) keeps working through the cutover without requiring the master key to exist before migration time. The `sys.exit`-on-missing-credential boot gate is replaced by a per-client `status` column computed at boot and on every integration write, closing survey criticals #3 (lost-on-deploy config) and #4 (one client's misconfiguration kills the platform).

## Architecture Decisions

| Decision | Choice | Alternatives Rejected | Rationale |
|----------|--------|------------------------|-----------|
| **P3-D1 — Two mutable tables, no revisions yet** | `client_integrations(id, client_id FK, provider, enabled, config JSON, status, status_reason, last_checked_at, created_at, created_by, updated_at, updated_by)` with `unique(client_id, provider)`; `client_secrets(id, client_id FK, integration_id FK nullable, name, ciphertext, key_id, created_at, created_by, updated_at, updated_by)` with `unique(client_id, name)`. Neither table is revisioned (no insert-only history table, no `active_revision_id` pointer) — both are mutated in place; audit trail is the `updated_by`/`updated_at` columns plus structured logs on every write. | (a) Mirror 1a/1b's `agent_config_revisions`/`client_config_revisions` immutable-revision pattern for both tables. (b) Revision `client_integrations` (config changes are rare, reviewable) but not `client_secrets`. | (a) is rejected for this phase specifically because CRM config edits and secret rotations are infrequent, low-blast-radius, single-value changes (an Airtable base ID, one API key) — not multi-field behavioral snapshots like an agent's full prompt/voice/model config where "what was active during this call" matters for debugging a live conversation. Building full revision history for a table nobody has asked to roll back yet is speculative scope within a phase whose stated goal (survey roadmap) is "DB instead of file, encrypted, no platform-wide boot failure" — none of which requires history. (b) was considered because secrets feel more sensitive, but mutable-with-audit-columns is already the chosen pattern for `client_integrations`, and splitting the two tables onto different durability models adds complexity (two different write-path shapes) for a benefit — secret-only history — nobody has asked for. Revisioning either table is an explicit, cheap future addition (same insert-only pattern already proven in 1a/1b) once a real need (e.g. "who changed this API key and when, show me the old one") appears. |
| **P3-D2 — Fernet/MultiFernet encryption, secrets never returned** | `cryptography`'s `MultiFernet` wraps a list of `Fernet` instances built from `QORA_SECRETS_MASTER_KEY` (comma-separated, first key encrypts new values, every key is tried on decrypt — standard key-rotation support). No API endpoint, log line, or error message ever includes a ciphertext or decrypted plaintext; every secret-bearing response exposes only `name`, `is_set: bool`, and `updated_at`. | (a) A single static key (no rotation support). (b) Envelope encryption via a cloud KMS (AWS KMS / GCP KMS). (c) Return a masked/truncated version of the secret (e.g. last 4 chars) for operator verification. | (a) blocks any future key rotation without a flag-day re-encryption of every row with no transition period — `MultiFernet`'s multi-key decrypt is the standard mitigation and costs nothing extra to adopt now. (b) is rejected as disproportionate: Qora has no existing cloud KMS integration, Railway (the deploy target per the task brief) has no native KMS binding, and adding a network dependency to every secret read would hurt the exact hot-path latency concern `IntegrationStore`'s cache is designed to avoid. (c) is rejected because even a masked suffix is a partial secret disclosure with no proven operational need — "is it set, and when was it last changed" (the chosen contract) answers every verification question an operator actually has without disclosing any part of the value. |
| **P3-D3 — Transitional resolution order: DB → env → degraded** | Resolving a client's CRM API key tries, in order: (1) a `client_secrets` row for that client/name, decrypted via `MultiFernet`, if `QORA_SECRETS_MASTER_KEY` is configured and decryption succeeds; (2) the legacy env var named in the integration's config (today's `CRMConfig.resolve_api_key` behavior, unchanged); (3) if neither resolves, the integration's status is set to `degraded` with a reason — never an exception that propagates past the integration boundary. When `QORA_SECRETS_MASTER_KEY` is absent entirely, the platform still boots normally; secret WRITES return 503 with a clear message (nothing is silently stored unencrypted); reads skip step 1 entirely and fall back straight to the env var. | (a) DB-only resolution, no env fallback — require every client to be migrated before cutover. (b) Env-only resolution with the DB tables existing but unused until a separate "go live" flag flips. | (a) would require importing every existing env-based secret into the DB atomically with the schema migration, at a moment when `QORA_SECRETS_MASTER_KEY` may not yet be configured in the deploy environment (it is a NEW env var this phase introduces) — that ordering dependency is exactly the kind of deploy-time coupling the roadmap is trying to remove, not add. (b) defers all actual value of this phase to a flag flip with no incremental verification path; the chosen transitional order lets task 8 verify the DB path against the one real secret (quintana-seguros Airtable) while every other (empty) client is provably unaffected, before any flag or cutover event. |
| **P3-D4 — No sys.exit for per-client problems; platform-level secrets keep hard-fail** | Boot computes, for every configured integration, a `status` (`ok` \| `degraded` \| `disabled`) and `status_reason`, persists it to `client_integrations`, and logs at `ERROR` for `degraded`. No per-client integration problem calls `sys.exit`. A degraded client's CRM tool calls (`tools/dispatcher.py`) return a clear tool-error string to the LLM ("CRM integration is not configured correctly for this client") instead of raising; every other call for that client, and every call for every other client, is unaffected. Qora-owned platform credentials (`OPENAI_API_KEY`, `ELEVENLABS_API_KEY`, `QORA_API_KEY` in production) are OUT of scope for this decision and keep their existing hard-fail validation — this decision narrows `validate_all_integration_credentials`'s per-client CRM check specifically, not `core/config.py`'s platform-credential validation. | (a) Keep `sys.exit` but only for the SPECIFIC client with the problem (e.g. refuse to serve that client's routes while others work). (b) Downgrade to a warning log only, no status tracking, no tool-level error. | (a) is not achievable with the platform's current single-process, single-deploy architecture — there is no per-client process boundary to selectively refuse; "don't serve this client" would require either a runtime route-level block (more complexity, and still a surprise 5xx to that client's callers with no clear message) or is simply a rename of the degraded-status approach already chosen, minus the clear tool-level error message. (b) is rejected because silent degradation without a visible status is worse than today's crash for operators — nobody would know a client's CRM integration silently stopped working until a customer complained; the survey's own critical #4 explicitly calls out "must not bring down the others," not "must not be visible," so status + logging is required, not optional. |
| **P3-D5 — `IntegrationStore` with write-through cache invalidation + short TTL safety net** | All CRM config reads (hot path: `voice/webhook.py` per-turn reads, `voice/context.py`, `tools/dispatcher.py`) go through `IntegrationStore.get(client_id)`, which checks an in-process `dict[client_id, (config, cached_at)]` cache before hitting the DB. Every write through the router API synchronously invalidates that client's cache entry. A short TTL (e.g. 30s) is a safety net for cache entries that outlive their process (multi-worker deploys) — not the primary invalidation mechanism. | (a) No cache — read the DB on every call. (b) A distributed cache (Redis) shared across worker processes. | (a) reintroduces exactly the per-turn filesystem-read cost `crm_config.py`'s own docstring already flags as a stall risk (`CRMConfigLoader.load_async`'s `asyncio.to_thread` comment) — swapping a filesystem stat+read for a DB round-trip on every voice turn is not an improvement, it is the same hot-path cost with a different I/O target. (b) is rejected as disproportionate for this phase: Qora's current deployment (confirmed via existing code, no Redis dependency anywhere in `backend/pyproject.toml`) has no shared-cache infrastructure, and introducing one here — for a CRM config that changes at most a few times per client's lifetime — is new infrastructure risk for a problem the TTL safety net already bounds (worst case: a multi-worker deploy's other workers see a stale config for up to the TTL window after a write, not indefinitely). |
| **P3-D6 — One-time import migration excludes secrets; admin import-from-env endpoint for secrets** | The schema migration chain's SECOND migration (`20261003_0022`) reads every `backend/clients/*/crm.yaml` and inserts a matching `client_integrations` row with the non-secret fields (`base_id`, `table_id`, `field_mappings`, `custom_fields`, `quote_ready_fields`, status maps, `enabled`). It does NOT read or write any `client_secrets` row. A separate admin endpoint, `POST /clients/{id}/integrations/{provider}/secrets/import-from-env`, reads the integration's configured env-var name, encrypts its current value, and inserts/updates the `client_secrets` row — callable only once an operator has configured `QORA_SECRETS_MASTER_KEY`. `crm.yaml` write paths are removed in task 5; the files themselves become read-only legacy artifacts (no longer read by any consumer after task 4) until task 7 deletes them entirely. | (a) Import secrets directly in the schema migration, assuming `QORA_SECRETS_MASTER_KEY` is already set. (b) Never import secrets automatically at all — require every secret to be re-entered manually through the panel. | (a) is rejected for the same deploy-ordering reason as P3-D3: Alembic migrations run automatically at the existing deploy entrypoint (confirmed house pattern), and a migration that hard-requires a NEW env var to exist, with no prior deploy to set it in advance, is a guaranteed first-deploy failure. House pattern also confirms migrations never import `app.*` — encryption logic lives in `app.core.crypto`, so a migration cannot call it directly even if the ordering were otherwise safe. (b) creates needless manual toil for the one real secret that exists today (quintana-seguros's Airtable key) and throws away a value the env var already holds safely; the explicit, operator-triggered import endpoint gets the same safety (nothing happens until the operator is ready) without discarding the existing value. |
| **P3-D7 — Keep the existing router contract, backed by the DB** | `crm_config_router.py`'s existing routes (`GET .../integrations`, `GET .../integrations/available`, `PUT .../integrations/{provider}`, `POST .../connect`, `POST .../test`, `DELETE .../disconnect`) keep their request/response shapes where the shape does not itself leak a secret; their implementation reads/writes `client_integrations`/`client_secrets` instead of `crm.yaml`. New endpoints are added, not substituted: `PUT .../integrations/{provider}/secret` (write-only, body `{value: str}`, response `{name, is_set, updated_at}`, never echoes the value), `GET .../integrations/{provider}/status` (returns `status`/`status_reason`/`last_checked_at`), and the import-from-env endpoint (P3-D6). Access control is unchanged: `require_client_access` at the router level, `require_superadmin` for the import-from-env and status-admin-detail paths, matching today's dependency wiring. | (a) Design a new API surface from scratch now that there's no filesystem constraint. (b) Fold the secret value into the existing `PUT .../integrations/{provider}` body as an `api_key` field, like `crm.yaml` does today. | (a) breaks every existing panel integration point for no behavioral gain — the filesystem-vs-DB change is an implementation detail the panel should not need to know about; keeping the contract is explicitly requested ("keep the existing crm_config_router routes/contract where possible") and consistent with 1a/1b's own precedent of staged, additive API evolution. (b) is rejected specifically because it is the CURRENT bug: `crm.yaml`'s `api_key` field is how a literal secret value ends up written to a file that gets discarded on deploy (survey critical #3) — a write-only, separately-routed secret endpoint is the structural fix, not a cosmetic one; mixing it back into the non-secret config PUT would silently reintroduce the same failure mode this phase exists to close. |

## Modified Requirement: Hard Startup Failure Is Superseded for Per-Client CRM Credentials

`openspec/changes/phase-b-secrets-management/specs/tenant-integration-secrets/spec.md`'s "Requirement: Startup Validation for Configured Integrations" currently states:

> "A missing credential for a configured, active integration MUST cause a hard startup failure with a clear error naming the client and the missing variable."

This phase **supersedes** that requirement for per-client CRM credentials specifically (not for Qora-owned global credentials, which that same spec's "Requirement: Qora Provider Credentials Are Not Per-Client Secrets" already scopes separately and which this change does not touch). The new behavior: a missing or invalid per-client CRM credential sets that integration's `status` to `degraded` with a `status_reason` naming the missing/invalid credential, logs at `ERROR`, and does NOT call `sys.exit`. See `specs/client-secrets/spec.md`'s "Requirement: Degraded Status Instead of Startup Failure" for the full behavioral contract this supersedes with.

**Rationale**: the original phase-b requirement was written and correct for a single-tenant mental model where one missing credential affecting "the application" was equivalent to affecting "the business." Qora is multi-tenant; the phase 3 roadmap goal — confirmed in the survey ("a misconfigured client must not bring down the others") — makes explicit that one client's credential problem must not be able to take every other client's calls down with it. The hard-fail behavior that was phase-b's safety guarantee has become, at multi-tenant scale, the platform's single largest availability risk from a single client's config mistake. This is not a safety regression: the credential problem is still surfaced loudly (status + `ERROR` log), just scoped to the one client and one integration it actually affects.

## Data Flow

```
READ PATH (hot path: per-turn voice reads, tool dispatch, runtime context)
───────────────────────────────────────────────────────────────────────────
IntegrationStore.get(client_id, provider="airtable")
       │
       ▼
   cache hit (and not expired)? ──yes──► return cached CRMConfig-shaped object
       │ no
       ▼
load client_integrations row (DB) → build CRMConfig-shaped object (non-secret fields)
       │
       ▼
cache the result (client_id → (config, cached_at))
       │
       ▼
return to caller
   (API key is NOT resolved here — callers needing it call resolve_api_key()
    separately, which performs the DB→env→degraded lookup on demand)


SECRET RESOLUTION (called only by code that needs the literal key, e.g. the
Airtable adapter — NOT on every config read)
───────────────────────────────────────────────────────────────────────────
resolve_client_secret(client_id, name)
       │
       ▼
   QORA_SECRETS_MASTER_KEY configured? ──no──► fall back to env var directly
       │ yes
       ▼
   client_secrets row exists for (client_id, name)? ──no──► fall back to env var
       │ yes
       ▼
   MultiFernet.decrypt(ciphertext) succeeds? ──no (log WARNING, do not raise)──► fall back to env var
       │ yes
       ▼
return decrypted value
       │
   (if BOTH DB and env fallback fail)
       ▼
mark integration status=degraded, status_reason="credential not resolvable", return None to caller


WRITE PATH — INTEGRATION CONFIG (non-secret)
──────────────────────────────────────────────
PUT /clients/{client_id}/integrations/{provider}
       │
       ▼
validate payload (existing CRMConfig/CRMFieldDef/CustomFieldDef Pydantic validation, reused as-is)
       │
       ▼
UPSERT client_integrations row (client_id, provider) — mutate in place, no revision row
       │
       ▼
IntegrationStore.invalidate(client_id)                 (P3-D5)
       │
       ▼
recompute status (does a secret already resolve? DB or env?) → persist status/status_reason


WRITE PATH — SECRET
─────────────────────
PUT /clients/{client_id}/integrations/{provider}/secret   { value: str }
       │
       ▼
   QORA_SECRETS_MASTER_KEY configured? ──no──► 503 "master key not configured"
       │ yes
       ▼
MultiFernet.encrypt(value) → ciphertext, key_id = fingerprint of first key
       │
       ▼
UPSERT client_secrets row (client_id, name) — mutate in place, no revision row
       │
       ▼
IntegrationStore.invalidate(client_id)
       │
       ▼
recompute status → persist; response body = { name, is_set: true, updated_at }  (value NEVER echoed)


BOOT VALIDATION (replaces sys.exit)
─────────────────────────────────────
for each client_integrations row where enabled=true:
    attempt secret resolution (DB → env, P3-D3)
       │
       ├─ resolves ──► status="ok", status_reason=None
       └─ fails ──► status="degraded", status_reason="<missing/invalid credential name>"
                    log ERROR (client_id, provider, reason)
                    (NO sys.exit — startup continues)
       │
       ▼
persist status to client_integrations; platform finishes booting regardless of any client's result
```

## File Changes

| File | Action | Description |
|------|--------|--------------|
| `backend/app/core/crypto.py` | Create | `MultiFernet` wrapper: `encrypt(value) -> (ciphertext, key_id)`, `decrypt(ciphertext) -> str`, built from `Settings.qora_secrets_master_key` |
| `backend/app/core/config.py` | Modify | `Settings.qora_secrets_master_key: str \| None = None` (comma-separated Fernet keys) |
| `backend/pyproject.toml` | Modify | Add `cryptography` dependency |
| `backend/app/tenants/models.py` | Modify | `ClientIntegration` model (`client_integrations` table); `ClientSecret` model (`client_secrets` table) |
| `backend/alembic/versions/20261003_0021_client_integrations_secrets_schema.py` | Create | `CREATE TABLE client_integrations`, `CREATE TABLE client_secrets`, both with `unique(client_id, ...)` constraints |
| `backend/alembic/versions/20261003_0022_import_crm_yaml_integrations.py` | Create | One-time import of every `backend/clients/*/crm.yaml`'s non-secret fields into `client_integrations`; no `app.*` import (house pattern — parses YAML inline) |
| `backend/app/integrations/integration_store.py` | Create | `IntegrationStore.get(client_id, provider)`, `.invalidate(client_id)`, `resolve_client_secret(client_id, name)` |
| `backend/app/integrations/crm_config.py` | Modify | `CRMConfig`/`CRMFieldDef`/`CustomFieldDef` kept as the shared Pydantic shapes; `CRMConfigLoader` marked legacy, superseded by `IntegrationStore`; ALL_CAPS regex moved to `core/credentials.py`, imported here |
| `backend/app/integrations/crm_config_router.py` | Modify | Write handlers call DB-backed service functions instead of `yaml.dump`; new secret/status/import-from-env endpoints added |
| `backend/app/integrations/crm_import_service.py` | Modify | Lines 171, 189 — `IntegrationStore.get(...)` / `resolve_client_secret(...)` instead of `CRMConfigLoader.load_async(...)` / `config.resolve_api_key()` |
| `backend/app/integrations/crm_sync_service.py` | Modify | Lines 69, 83 — same cutover |
| `backend/app/tools/dispatcher.py` | Modify | Lines 42, 135, 188 — same cutover; degraded-status integration returns a tool-error string instead of raising |
| `backend/app/tools/registry.py` | Modify | Line 154 — same cutover |
| `backend/app/voice/webhook.py` | Modify | Lines ~1012, 1104, 1147, 1225 — per-turn reads go through `IntegrationStore`'s cache |
| `backend/app/voice/context.py` | Modify | Lines 404–411 — same cutover |
| `backend/app/summarizer.py` | Modify | Line 1172 — same cutover |
| `backend/app/core/credentials.py` | Modify | `validate_all_integration_credentials` computes/persists per-client `status` instead of calling `sys.exit`; hosts the single shared ALL_CAPS regex helper |
| `backend/clients/*/crm.yaml` | Delete (task 7) | Removed once no reader touches the filesystem path |

## Interfaces / Contracts

```python
# backend/app/core/crypto.py
class SecretCrypto:
    """MultiFernet-backed encrypt/decrypt, keyed from QORA_SECRETS_MASTER_KEY."""

    def __init__(self, master_keys: list[str]) -> None: ...

    def encrypt(self, plaintext: str) -> tuple[bytes, str]:
        """Returns (ciphertext, key_id). key_id identifies which key encrypted it
        (fingerprint of the first/active key) for future rotation auditing."""

    def decrypt(self, ciphertext: bytes) -> str:
        """Raises InvalidToken if no configured key can decrypt it. Never logs
        the ciphertext or the decrypted value."""


def get_secret_crypto() -> SecretCrypto | None:
    """Returns None if QORA_SECRETS_MASTER_KEY is not configured — callers
    MUST handle None by falling back to env resolution (P3-D3), never by
    raising."""
```

```python
# backend/app/integrations/integration_store.py
class IntegrationStore:
    """Single read path for per-client CRM config. In-process cache,
    write-through invalidation, short TTL safety net (P3-D5)."""

    async def get(self, client_id: str, provider: str = "airtable") -> CRMConfig | None:
        """Returns the same CRMConfig shape CRMConfigLoader.load_async returned,
        sourced from client_integrations instead of crm.yaml. None if no
        integration is configured for this client (same semantics as a
        missing crm.yaml today)."""

    def invalidate(self, client_id: str) -> None:
        """Synchronous; called by every write-path endpoint after a successful
        UPSERT."""


async def resolve_client_secret(client_id: str, name: str) -> str | None:
    """DB -> env -> None (P3-D3). Never raises on a missing/undecryptable
    secret; the caller (IntegrationStore / dispatcher) is responsible for
    setting the integration's degraded status when this returns None for an
    enabled integration."""
```

```python
# backend/app/tenants/models.py — new models
class ClientIntegration(Base):
    __tablename__ = "client_integrations"
    __table_args__ = (UniqueConstraint("client_id", "provider"),)
    id: Mapped[str]
    client_id: Mapped[str]            # FK clients.id
    provider: Mapped[str]             # "airtable", future: "hubspot", ...
    enabled: Mapped[bool]
    config: Mapped[str]               # JSON/Text — base_id, table_id, field_mappings,
                                       # custom_fields, quote_ready_fields, status maps
    status: Mapped[str]               # "ok" | "degraded" | "disabled"
    status_reason: Mapped[str | None]
    last_checked_at: Mapped[datetime | None]
    created_at: Mapped[datetime]
    created_by: Mapped[str]
    updated_at: Mapped[datetime]
    updated_by: Mapped[str]


class ClientSecret(Base):
    __tablename__ = "client_secrets"
    __table_args__ = (UniqueConstraint("client_id", "name"),)
    id: Mapped[str]
    client_id: Mapped[str]            # FK clients.id
    integration_id: Mapped[str | None]  # FK client_integrations.id, nullable
    name: Mapped[str]                 # e.g. "airtable_api_key"
    ciphertext: Mapped[bytes]
    key_id: Mapped[str]               # which master key encrypted this row
    created_at: Mapped[datetime]
    created_by: Mapped[str]
    updated_at: Mapped[datetime]
    updated_by: Mapped[str]
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|---------------|----------|
| Unit | `SecretCrypto` encrypt/decrypt round-trip | Encrypt a value, decrypt it, assert equality; assert ciphertext bytes never equal the plaintext; assert `decrypt` raises on a value encrypted with a key not in the current list |
| Unit | `MultiFernet` rotation | Encrypt with key A only; add key B as first, keep A second; assert the old ciphertext still decrypts; assert new encryptions use key B's `key_id` |
| Unit | `IntegrationStore` cache coherence | A `get()` after a write (without calling `.invalidate()` manually — the write path calls it) reflects the new value; a `get()` within the TTL window without any write returns the cached value without a DB hit (assert via a DB-call counter/mock) |
| Unit | `resolve_client_secret` resolution order | DB value present + master key configured → DB value returned; DB absent + env var set → env value returned; both absent → `None` returned, no exception |
| Unit | Master-key-absent write behavior | `PUT .../secret` with no `QORA_SECRETS_MASTER_KEY` configured → 503, clear message, no row written |
| Unit | Secret API never echoes the value | `PUT .../secret` response body contains only `name`, `is_set`, `updated_at` — assert the literal submitted value string does not appear anywhere in the response JSON |
| Integration | Config survives a simulated redeploy | Write a `client_integrations` row via the API, restart the app process (new `IntegrationStore` instance) against the SAME DB, assert the config is still read back correctly — the literal regression test for survey critical #3 |
| Integration | Degraded client does not affect others | Two clients, one with a valid secret and one with a missing one; assert the valid client's CRM tool calls succeed and the invalid client's CRM tool calls return a tool-error string, with NO exception raised and NO impact on the valid client's calls — the literal regression test for survey critical #4 |
| Integration | Boot validation sets status, never exits | Run `validate_all_integration_credentials` equivalent against a DB with one `enabled=true` integration whose secret does not resolve; assert the process does NOT exit (no `SystemExit` raised) and the row's `status` becomes `degraded` with a non-null `status_reason` |
| Integration | One-time import migration | Run the migration against a tmp DB seeded with a fixture `crm.yaml`; assert the resulting `client_integrations` row's non-secret fields match the YAML, and assert NO `client_secrets` row is created by this migration |
| Integration | Import-from-env endpoint | Call `POST .../secrets/import-from-env` with the master key configured and the named env var set; assert a `client_secrets` row is created/updated and `resolve_client_secret` subsequently returns the DB value (not falling through to env) |
| Regression | Every known reader cut over | A static-import test (task 7's RED test) asserts no remaining `from app.integrations.crm_config import CRMConfigLoader` import exists anywhere under `backend/app/` once task 7 lands |
| Regression | Existing CRM test suite still passes | `backend/tests/.../test_crm_*.py` (confirmed existing suite covering `CRMConfig`, the router, import/sync services) continues to pass against the new DB-backed implementation, adjusted only where the test directly asserted a `crm.yaml` filesystem write (those specific assertions are updated to assert the DB row instead, not removed) |

## Migration / Rollout

**Staged rollout** (see tasks.md for full per-task RED/GREEN/rollback breakdown):

1. Crypto module + settings + `cryptography` dependency — additive, nothing reads it yet
2. Schema + one-time import migration — additive; `client_integrations` populated from existing `crm.yaml` files, `client_secrets` stays empty
3. `IntegrationStore` + cache + secret resolution — additive, nothing calls it yet
4. Cut over every reader — the only reader-facing behavioral change; existing CRM functionality must be bit-for-bit equivalent (same config values, same resolved secret) before and after
5. Router writes to the DB; secret/status/import-from-env endpoints added — `crm.yaml` write paths removed, files become legacy-only
6. Boot validation → degraded status, `sys.exit` removed — gated on task 4 being stable (status computation depends on the same resolution path readers use)
7. Remove `crm.yaml` files + dedupe the ALL_CAPS regex — only after task 4's RED test (no remaining `CRMConfigLoader` import) passes
8. Prod rollout: set `QORA_SECRETS_MASTER_KEY` in Railway, call the import-from-env endpoint for quintana-seguros's Airtable key, verify via the status endpoint and a live tool call

**Existing-client safe path**: quintana-seguros is the only client with a real `crm.yaml` today (confirmed). The import migration (task 2) creates its `client_integrations` row automatically; its secret stays env-resolved (P3-D3) until task 8 explicitly imports it. No behavior change is observable to that client until task 8's explicit import step, which is independently verifiable via the status endpoint before and after.

## Rollback Plan

| Stage | Action | Notes |
|-------|--------|-------|
| After task 1 (crypto + dependency) | Revert PR; remove dependency line | Pure addition, no data impact |
| After task 2 (schema + import migration) | `alembic downgrade -1` twice (import migration, then schema migration) | No runtime code depends on either table yet |
| After task 3 (`IntegrationStore`) | Revert PR | Pure addition, nothing calls it yet |
| After task 4 (reader cutover) | Revert PR | Every reader reverts to `CRMConfigLoader`/`crm.yaml`, untouched and still on disk |
| After task 5 (router write cutover) | Revert PR | `crm_config_router.py` reverts to `yaml.dump`; `client_integrations`/`client_secrets` rows written during the rollback window are simply unused, not corrupting anything |
| After task 6 (boot validation) | Revert PR | `validate_all_integration_credentials` reverts to `sys.exit` — an explicit regression of this phase's own goal, acceptable only as an emergency rollback |
| After task 7 (file removal + dedupe) | Revert PR restores `crm.yaml` files from git history | Only attempted after task 4-6 are proven stable in review |
| After task 8 (prod rollout) | Unset `QORA_SECRETS_MASTER_KEY` (resolution falls back to env, matching pre-phase-3 behavior); re-run task 6's revert if the degraded-status behavior itself is the problem | Additive-only posture up to this point |

## Open Questions

- [ ] Should `client_integrations`/`client_secrets` gain revision history (P3-D1's deferred alternative) once a client's panel usage shows edits are frequent enough to need rollback? Not blocking any task 1–8; revisit if an operator asks "what was this API key last week."
- [ ] Exact `key_id` format for `MultiFernet` rotation auditing (fingerprint vs. explicit operator-assigned label) — a fingerprint is sufficient for task 1-8's scope; an operator-assigned label (e.g. `"2026-Q4"`) might read better in the status endpoint but is a naming choice, not a blocking design decision.
- [ ] Whether the short cache TTL (P3-D5) should be configurable per-deployment via `Settings` or a fixed constant — fixed (e.g. 30s) is sufficient for the single-worker-process deploy target confirmed in this phase; revisit only if Qora moves to a multi-worker/multi-process deployment where cross-process staleness becomes observable in practice.
