# Configuration Phase 3 — Client Integrations and Encrypted Secrets

Goal: implement `openspec/changes/client-integrations-secrets`. The CRM config and per-client API keys move to the DB (secrets encrypted), so panel edits survive deploys and one misconfigured client cannot bring the platform down (survey critical defects #3 and #4).

Branch `feat/config-phase3` from `main` `e828fe0`. Overnight autonomous run (the user is asleep): the user reviews in the morning. Not deployed.

## Tasks

- [x] 1. Phases 1 + 2: `cryptography` dependency, `QORA_SECRETS_MASTER_KEY` setting, `SecretCrypto`; `client_integrations` / `client_secrets` models, schema migration 0021, crm.yaml import migration 0022.
- [x] 2. Phase 3: `IntegrationStore` with cache, and secret resolution in DB → env → missing order.
- [x] 3. Phase 4: cut every reader over to the store (import, sync, tools, voice hot path, summarizer) plus the static-import guard.
- [x] 4. Phase 5: router writes to the DB; write-only secret, status and import-from-env endpoints.
- [x] 5. Phase 6 + 7.1: boot validation gives a per-client degraded status instead of `sys.exit`; two-client isolation proof; deduplicate the env-name regex.
- [ ] 6. Full suites green; production rollout notes.

Deferred on purpose: task 7.2 (delete `backend/clients/*/crm.yaml`). Migration 0022 reads those files at deploy time, so they can only be deleted in a release AFTER production has run 0022.

## Evidence

- Design commit `0b90845` (proposal, design P3-D1..D7, tasks, 2 specs). Parent decisions: per-client degraded status supersedes the phase-b hard-fail (the survey explicitly asks for it); no revisions for secrets; Fernet/MultiFernet master key from env with fallback to the legacy env var while the key is absent.
- Task 1: `cryptography` added; `qora_secrets_master_key` (SecretStr); `core/crypto.py` SecretCrypto (MultiFernet, key_id); `ClientIntegration` / `ClientSecret` models; migrations 0021 (schema) and 0022 (crm.yaml import: non-secret config plus `legacy_env_var_name`, no secret values, idempotent, no app.* imports). RED observed (the 2.2 RED was captured by temporarily renaming the file, disclosed). Real-data copy: the quintana-seguros airtable row was imported with `legacy_env_var_name=QUINTANA_AIRTABLE_API_KEY` and 0 secrets. Worker full suite: 3873 passed.
- Task 2: `IntegrationStore.get(session, client_id, provider)` with a 30 s cache and `invalidate`; `resolve_client_secret` (DB → legacy env → None; the DB is skipped without a master key); `CRMConfig.legacy_env_var_name`, `api_key` optional with a validator, `resolve_api_key_async`. RED observed (10 tests). Worker full suite: 3883 passed.
- Task 3: every reader (import, sync, capture_data tool, voice context, the 4 webhook sites, summarizer) moved to `IntegrationStore`. The webhook fast path checks `peek_cached` and opens a session only on a cache miss. Degraded mode: the tool returns `crm_unavailable`, jobs log and skip. Fixed ruff undefined `CRMConfig` in registry.py. Tests moved from tmp crm.yaml to DB rows; new static guard (excludes crm_config_router.py, phase 5, and leads/router.py:349, still a CRMConfigLoader reader and closed in task 4). Worker full suite: 3879 passed. Parent fix: negative cache, because clients without a CRM were opening a DB session on every turn (new test; its RED was not clean because the stash also removed peek_cached, but GREEN covers the logic); integrations/voice/tools: 474 passed.
- Task 4: crm_config_router.py now writes to the DB (the request and response contracts are kept; no more crm.yaml writes; the cache is invalidated after every write). New endpoints: PUT `.../{provider}/secret` (write-only, 503 without a master key), GET `.../status` (secret source db/env/missing, no values), POST `.../secrets/import-from-env` (superadmin). `recompute_and_persist_status` added. leads/router.py moved to the store; the guard now allows zero CRMConfigLoader importers (the class stays, as legacy with its own tests). Secret name: reuse `legacy_env_var_name`, else `{provider}_api_key`. Tests check that secrets are never echoed or logged. Worker full suite: 3884 passed.
- Task 5: `validate_all_integration_credentials` is now async and DB-based. It recomputes and persists each integration's status, logs degraded clients, and never exits; it runs after `init_db` in main.py. The platform credentials (OPENAI, ELEVENLABS, QORA_API_KEY) still hard-fail in `Settings` (a test proves it). Two-client isolation test; startup smoke test with a degraded client; the env-name regex has a single definition (guard test). RED: not captured edit by edit (baseline = the old tests, disclosed). Worker full suite: 3873 passed (the count dropped because obsolete crm.yaml credential tests were rewritten).
