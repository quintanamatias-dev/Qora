# Tasks: Qora Config Phase 3 — Client Integrations & Secrets

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~2,100 total across 8 units |
| 800-line budget risk | High if combined; Low per-unit when kept separate |
| 400-line budget risk | Low — every unit estimated at or under ~400 lines |
| Chained PRs recommended | Yes — eight review slices, strictly ordered |
| Suggested split | One PR per numbered task below; task 4 (reader cutover) and task 6 (boot validation) are never combined with any other task |
| Delivery strategy | auto-forecast |
| Chain strategy | stacked-to-main |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Crypto module + settings + `cryptography` dependency | PR 1 | Additive; no dependents yet. Rollback: revert PR, remove dependency line. |
| 2 | Schema + one-time crm.yaml import migration | PR 2 | Additive; depends on PR 1 only for the `cryptography` dependency being present (not used by the migration itself — migrations never import `app.*`). Rollback: `alembic downgrade -1` twice. |
| 3 | `IntegrationStore` + cache + secret resolution | PR 3 | Additive; depends on PR 1-2. Rollback: revert PR. |
| 4 | Cut over all readers | PR 4 | Behavioral-equivalence cutover — never combined with another task. Depends on PR 1-3. Rollback: revert PR. |
| 5 | Router writes to DB + secret/status/import endpoints | PR 5 | Depends on PR 1-4. Rollback: revert PR. |
| 6 | Boot validation → degraded status, remove `sys.exit` | PR 6 | Never combined with another task — the core safety-model change. Depends on PR 3-5. Rollback: revert PR. |
| 7 | Remove `crm.yaml` files + dedupe ALL_CAPS regex | PR 7 | Depends on PR 4 and PR 6 both being stable. Rollback: revert PR, restores files from git history. |
| 8 | Prod rollout: `QORA_SECRETS_MASTER_KEY`, import-from-env, verify | PR 8 | Depends on all prior tasks. Rollback: unset master key, falls back to env. |

## Known Environmental Failures

None identified at the time of writing — this change's own test additions are the only expected RED states before implementation. If the base backend suite has pre-existing unrelated failures at apply time, they must be named explicitly here before any task reports `status: completed`.

## Phase 1: Crypto Module + Settings + Dependency

- [ ] 1.1 Add `cryptography` to `backend/pyproject.toml`.
      RED: `test_cryptography_is_importable` (new file `backend/tests/unit/core/test_crypto.py`) — fails (package not installed).
      GREEN: `from cryptography.fernet import Fernet, MultiFernet` succeeds.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/core/test_crypto.py -k importable`
      Rollback: remove the dependency line; revert commit.

- [ ] 1.2 Add `Settings.qora_secrets_master_key: str | None = None` to `backend/app/core/config.py` (comma-separated Fernet keys, no validation beyond presence — malformed keys fail at `SecretCrypto` construction, not at `Settings` load).
      RED: `test_settings_accepts_master_key_env_var` — fails (field doesn't exist).
      GREEN: setting `QORA_SECRETS_MASTER_KEY=<valid-fernet-key>` in the environment populates `Settings().qora_secrets_master_key`; unset env var → `None`, no error.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/core/test_crypto.py -k settings`
      Rollback: remove the field; revert commit.

- [ ] 1.3 Create `backend/app/core/crypto.py` with `SecretCrypto` (`MultiFernet`-backed `encrypt`/`decrypt`) and `get_secret_crypto() -> SecretCrypto | None`.
      RED: `test_secret_crypto_round_trip`, `test_secret_crypto_rotation_decrypts_old_key`, `test_get_secret_crypto_returns_none_without_master_key` — all fail (module doesn't exist).
      GREEN: encrypt→decrypt round-trip returns the original plaintext; a value encrypted with an old key (no longer first in the list) still decrypts once added back to the key list; `get_secret_crypto()` returns `None` when `qora_secrets_master_key` is unset, never raises.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/core/test_crypto.py`
      Rollback: delete the file; revert commit.

## Phase 2: Schema + One-Time Import Migration

- [ ] 2.1 Add `ClientIntegration` and `ClientSecret` models to `backend/app/tenants/models.py` per design.md's Interfaces/Contracts section.
      RED: `test_client_integration_model_fields_exist`, `test_client_secret_model_fields_exist` (new file `backend/tests/unit/tenants/test_client_integration_secret_models.py`) — fail (models don't exist).
      GREEN: both models import successfully; `unique(client_id, provider)` and `unique(client_id, name)` constraints are present via `PRAGMA index_list`/model metadata.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/tenants/test_client_integration_secret_models.py`
      Rollback: delete the model classes; revert commit.

- [ ] 2.2 Create `backend/alembic/versions/20261003_0021_client_integrations_secrets_schema.py` (chained after `20261003_0020_delete_qora_demo_tenant.py`): `CREATE TABLE client_integrations`, `CREATE TABLE client_secrets`.
      RED: `test_client_integrations_secrets_schema_migration_creates_tables` — fails against a tmp DB at the current head (tables do not exist).
      GREEN: `alembic upgrade head` on a tmp DB creates both tables with the expected columns and unique constraints (`PRAGMA table_info` / `PRAGMA index_list`).
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/test_alembic_tooling.py -k client_integrations_secrets_schema`
      Rollback: `alembic downgrade -1` on the tmp DB; remove the revision file.

- [ ] 2.3 Create `backend/alembic/versions/20261003_0022_import_crm_yaml_integrations.py`: for each `backend/clients/*/crm.yaml`, insert a `client_integrations` row with the non-secret fields. No `app.*` import (house pattern — parse YAML inline with `yaml.safe_load`); no `client_secrets` row created by this migration.
      RED: `test_import_crm_yaml_migration_creates_integration_row_from_fixture` — fails (migration doesn't exist); fixture uses a tmp `crm.yaml` matching quintana-seguros's real shape.
      GREEN: after `alembic upgrade head`, a `client_integrations` row exists for the fixture client with `base_id`/`table_id`/`field_mappings`/`custom_fields`/`quote_ready_fields` matching the YAML; assert ZERO rows exist in `client_secrets`.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/test_alembic_tooling.py -k import_crm_yaml`
      Rollback: `alembic downgrade -1` on the tmp DB; remove the revision file.

## Phase 3: IntegrationStore + Cache + Secret Resolution

- [ ] 3.1 Create `backend/app/integrations/integration_store.py` with `IntegrationStore.get(client_id, provider)` reading `client_integrations`, returning the existing `CRMConfig` Pydantic shape (reused from `crm_config.py`, not redefined).
      RED: `test_integration_store_get_returns_crm_config_shape`, `test_integration_store_get_returns_none_when_not_configured` (new file `backend/tests/unit/integrations/test_integration_store.py`) — fail (class doesn't exist).
      GREEN: a seeded `client_integrations` row round-trips through `.get()` into a `CRMConfig` instance with matching fields; a client with no row returns `None` (same semantics as a missing `crm.yaml` today).
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/integrations/test_integration_store.py -k get`
      Rollback: delete the file; revert commit.

- [ ] 3.2 Add write-through cache + short TTL safety net to `IntegrationStore`; add `.invalidate(client_id)`.
      RED: `test_integration_store_cache_hit_skips_db`, `test_integration_store_invalidate_forces_db_reread`, `test_integration_store_ttl_expires_cache` — fail (cache doesn't exist, every `.get()` hits the DB).
      GREEN: a second `.get()` call within the TTL window does not re-query the DB (assert via a DB-call counter/mock); calling `.invalidate(client_id)` then `.get()` re-queries and reflects an updated row; a `.get()` call after the TTL window re-queries even without an explicit invalidate.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/integrations/test_integration_store.py -k cache`
      Rollback: revert the cache-specific commit; `.get()` reverts to always hitting the DB (functionally correct, just slower — safe intermediate state).

- [ ] 3.3 Add `resolve_client_secret(client_id, name) -> str | None` implementing the DB → env → `None` order (P3-D3), plus the master-key-absent fallback.
      RED: `test_resolve_client_secret_prefers_db_when_configured`, `test_resolve_client_secret_falls_back_to_env`, `test_resolve_client_secret_returns_none_when_neither_resolves`, `test_resolve_client_secret_skips_db_when_master_key_absent` — fail (function doesn't exist).
      GREEN: all four scenarios resolve exactly as named, with no exception raised in any case; a `WARNING` log line is emitted when the env fallback path is used (greppable for task 8's rollout visibility).
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/integrations/test_integration_store.py -k resolve_client_secret`
      Rollback: delete the function; revert commit.

## Phase 4: Cut Over All Readers (do not combine with other tasks)

- [ ] 4.1 Cut over `backend/app/integrations/crm_import_service.py` (lines 171, 189) to `IntegrationStore.get(...)` / `resolve_client_secret(...)` instead of `CRMConfigLoader.load_async(...)` / `config.resolve_api_key()`.
      RED: existing `backend/tests/.../test_crm_import_service.py` tests that assert a `crm.yaml`-backed config is read — adjusted to seed a `client_integrations`/`client_secrets` row instead of a fixture file; these fail against the unmodified source (still reading the filesystem).
      GREEN: the same tests pass reading from the DB fixtures; no remaining `CRMConfigLoader` import in this file.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/integrations/test_crm_import_service.py`
      Rollback: revert the file to its `CRMConfigLoader` import; `crm.yaml` is untouched and still present on disk.

- [ ] 4.2 Cut over `backend/app/integrations/crm_sync_service.py` (lines 69, 83).
      RED/GREEN: same pattern as 4.1, against `test_crm_sync_service.py`.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/integrations/test_crm_sync_service.py`
      Rollback: same pattern as 4.1.

- [ ] 4.3 Cut over `backend/app/tools/dispatcher.py` (lines 42, 135, 188) and `backend/app/tools/registry.py` (line 154); add the degraded-status tool-error-string path.
      RED: existing dispatcher/registry CRM-tool tests, plus a NEW `test_degraded_integration_returns_tool_error_not_exception` — fail (no degraded-status handling exists yet; dispatcher still imports `CRMConfigLoader`).
      GREEN: existing tests pass against `IntegrationStore`; the new test asserts a client with `status=degraded` gets a clear tool-error string from a CRM tool call, with no exception raised and no impact on a sibling client's calls in the same test (the literal survey-critical-#4 regression test).
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/tools/test_dispatcher.py tests/unit/tools/test_registry.py`
      Rollback: revert both files to their `CRMConfigLoader` imports.

- [ ] 4.4 Cut over `backend/app/voice/webhook.py` (lines ~1012, 1104, 1147, 1225) and `backend/app/voice/context.py` (lines 404–411).
      RED: existing webhook/context CRM-config tests — fail against the unmodified source once their fixtures are switched to DB-seeded rows.
      GREEN: same tests pass reading via `IntegrationStore`; per-turn reads use the cache (assert via a DB-call-count test that a simulated multi-turn conversation issues at most one DB read per cache TTL window, not one per turn).
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/voice/test_webhook.py tests/unit/voice/test_context.py`
      Rollback: revert both files to their `CRMConfigLoader` imports.

- [ ] 4.5 Cut over `backend/app/summarizer.py` (line 1172).
      RED/GREEN: same pattern as 4.1, against the existing summarizer CRM-config test.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/test_summarizer.py -k crm`
      Rollback: same pattern as 4.1.

- [ ] 4.6 Static-import regression guard: no remaining `from app.integrations.crm_config import CRMConfigLoader` import anywhere under `backend/app/` (the gate task 7 depends on).
      RED: `test_no_remaining_crm_config_loader_imports` (new file `backend/tests/unit/test_crm_config_loader_removed.py`) — fails until 4.1-4.5 are all complete.
      GREEN: a source-grep-based test over `backend/app/` finds zero matches.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/test_crm_config_loader_removed.py`
      Rollback: n/a — verification-only guard test; a failure here means a reader was missed, not that this task itself needs reverting.

## Phase 5: Router Writes to DB + Secret/Status/Import Endpoints

- [ ] 5.1 Cut over `PUT /clients/{client_id}/integrations/{provider}`, `POST .../connect`, `DELETE .../disconnect` in `crm_config_router.py` to UPSERT/DELETE `client_integrations` rows instead of `yaml.dump`/file delete; call `IntegrationStore.invalidate(client_id)` after every write.
      RED: existing router tests asserting a `crm.yaml` file is written/deleted — adjusted to assert a `client_integrations` row instead; fail against the unmodified source.
      GREEN: the same request/response contract (status codes, body shape) is preserved; the underlying write lands in the DB; a `GET` immediately after reflects the change (cache invalidation confirmed).
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/integrations/test_crm_config_router.py`
      Rollback: revert the file; writes go back to `yaml.dump`.

- [ ] 5.2 Add `PUT /clients/{client_id}/integrations/{provider}/secret` (write-only, body `{value: str}`, response `{name, is_set, updated_at}`), returning 503 when `QORA_SECRETS_MASTER_KEY` is not configured.
      RED: `test_put_secret_encrypts_and_stores`, `test_put_secret_response_never_echoes_value`, `test_put_secret_returns_503_without_master_key` — fail (endpoint doesn't exist, 404).
      GREEN: all three scenarios behave exactly as named; a log-capture assertion confirms the submitted value never appears in any log line emitted during the request.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/integrations/test_crm_config_router.py -k secret`
      Rollback: remove the route handler; revert commit.

- [ ] 5.3 Add `GET /clients/{client_id}/integrations/{provider}/status` (returns `status`, `status_reason`, `last_checked_at`).
      RED: `test_get_integration_status_returns_current_state` — fails (endpoint doesn't exist).
      GREEN: response matches the `client_integrations` row's persisted status fields.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/integrations/test_crm_config_router.py -k status`
      Rollback: remove the route handler; revert commit.

- [ ] 5.4 Add `POST /clients/{client_id}/integrations/{provider}/secrets/import-from-env` (superadmin-gated, P3-D6).
      RED: `test_import_from_env_requires_superadmin`, `test_import_from_env_encrypts_current_env_value`, `test_import_from_env_without_master_key_returns_503` — fail (endpoint doesn't exist).
      GREEN: a non-superadmin request is rejected (403); a superadmin request with the master key configured creates/updates the `client_secrets` row and `resolve_client_secret` subsequently returns the DB value, not the env fallback; without the master key, 503.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/integrations/test_crm_config_router.py -k import_from_env`
      Rollback: remove the route handler; revert commit.

## Phase 6: Boot Validation → Degraded Status (do not combine with other tasks)

- [ ] 6.1 Rewrite `validate_all_integration_credentials` (`backend/app/core/credentials.py`) to compute and persist per-client `status`/`status_reason` instead of calling `sys.exit`; retains its "clients without a configured integration are silently skipped" and "disabled integrations are silently skipped" behavior unchanged.
      RED: `test_boot_validation_sets_degraded_status_no_sys_exit`, `test_boot_validation_does_not_exit_on_missing_credential` (extends `backend/tests/unit/core/test_credentials.py`) — fail against the unmodified source (current behavior calls `sys.exit`, asserted via `pytest.raises(SystemExit)` today — that assertion is REPLACED, not merely silenced, since the old behavior is the thing being removed).
      GREEN: a client with an unresolvable CRM credential boots successfully (no `SystemExit` raised anywhere in the test); that client's `client_integrations.status` becomes `degraded` with a non-null `status_reason`; an `ERROR`-level log line is emitted naming the client and the missing credential.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/core/test_credentials.py`
      Rollback: revert the file to its `sys.exit` behavior — explicit regression of this phase's goal, acceptable only as an emergency rollback.

- [ ] 6.2 Two-client isolation regression test (the literal survey-critical-#4 proof): one client with a valid credential, one with a missing one, both configured; assert the valid client's own `status=ok` and its CRM tool calls succeed, completely independent of the other client's `degraded` state.
      RED: `test_one_client_degraded_does_not_affect_sibling_client` — fails if any shared global state (e.g. a single boot-wide exception, a shared cache keyed wrong) couples the two clients' outcomes.
      GREEN: both clients' `client_integrations.status` values are independently correct; no cross-client interference observed.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/core/test_credentials.py -k isolation`
      Rollback: n/a — regression guard; a failure here blocks closing task 6, it does not require reverting unrelated code.

- [ ] 6.3 Confirm `backend/app/main.py`'s startup call site (`validate_all_integration_credentials()`, line ~131) requires no signature change; add a smoke test that the FastAPI app starts (TestClient construction) with a seeded degraded client in the DB.
      RED: `test_app_starts_with_degraded_client_in_db` — fails if any import-time or startup-event code path still assumes the old `sys.exit`-or-success binary outcome.
      GREEN: `TestClient(app)` construction succeeds with a degraded client present.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/test_main_startup.py -k degraded`
      Rollback: n/a — verification-only; a failure here is evidence for task 6.1, not a separate revert.

## Phase 7: Remove crm.yaml Files + Dedupe ALL_CAPS Regex

- [ ] 7.1 Move the ALL_CAPS env-var-name regex (`^[A-Z][A-Z0-9_]+$`) and its `_looks_like_env_var_name` helper into `backend/app/core/credentials.py` as the single shared definition; `crm_config.py` and `crm_config_router.py` import it instead of redefining it.
      RED: `test_all_caps_regex_defined_in_exactly_one_module` (new file `backend/tests/unit/core/test_env_var_regex_dedupe.py`) — fails (three independent regex definitions exist today, confirmed via grep).
      GREEN: a source-grep-based test confirms the pattern literal `[A-Z][A-Z0-9_]+` (or the compiled regex object) is defined in exactly one module, imported everywhere else.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/core/test_env_var_regex_dedupe.py`
      Rollback: revert the import changes; each file reverts to its own local regex definition (functionally identical, just duplicated again).

- [ ] 7.2 Delete `backend/clients/*/crm.yaml` files; gated on task 4.6's static-import guard passing (no remaining `CRMConfigLoader` import) AND task 6 being merged and stable.
      RED: re-run task 4.6's `test_no_remaining_crm_config_loader_imports` as the gate — must already be green before this task starts.
      GREEN: `crm.yaml` files no longer exist under `backend/clients/`; full backend suite still passes (no test fixture still depends on the filesystem files).
      Check: `cd backend && uv run pytest -q -p no:cacheprovider` (full suite)
      Rollback: `git revert` restores the deleted files from history.

## Phase 8: Prod Rollout + Verification

- [ ] 8.1 Set `QORA_SECRETS_MASTER_KEY` in Railway's production environment (generate via `Fernet.generate_key()`, store as a single-key comma-separated value for the initial rollout).
      Check: API call to any status endpoint confirms the app is still serving after the env var is added and the app restarts (Railway's normal deploy cycle, no SSH).
      Rollback: unset the env var; resolution falls back to env entirely (matching pre-phase-3 behavior), no data loss since no secret has been imported yet at this point.

- [ ] 8.2 Call `POST /clients/quintana-seguros/integrations/airtable/secrets/import-from-env` (superadmin-authenticated) to copy the existing `QUINTANA_AIRTABLE_API_KEY` env value into `client_secrets`, encrypted.
      Check: subsequent `GET .../integrations/airtable/status` shows `status=ok`; a live CRM tool call (e.g. `capture_data` against the real Airtable base, per existing verification precedent) succeeds, confirming `resolve_client_secret` now returns the DB-sourced value.
      Rollback: delete the `client_secrets` row via direct DB access if available, or simply leave it — the env fallback remains intact and unaffected either way, so this step is non-destructive.

- [ ] 8.3 Verify no other client was affected by the rollout: confirm every other `client_integrations` row's `status` is unchanged from its pre-rollout value via the status endpoint.
      Check: `GET .../integrations/{provider}/status` for every configured client, compared against a pre-rollout snapshot.
      Rollback: n/a — verification only.

- [ ] 8.4 Run the full backend suite one final time before closing the change.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider`
      Rollback: n/a — verification gate; any failure blocks closing the change until fixed or explicitly triaged as pre-existing/unrelated.
