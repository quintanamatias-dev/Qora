# Apply Progress: Airtable CRM Integration

**Change**: airtable-crm-integration
**Mode**: Strict TDD
**Chain strategy**: stacked-to-main
**Batches completed**: 3 of 3

---

## Completed Tasks (PR 1 — Config + Field Mapping Foundation)

- [x] 1.1 RED: `backend/tests/unit/integrations/test_crm_config.py` — 9 tests covering FM-1 through FM-4, FM-6
- [x] 1.2 GREEN: `backend/app/integrations/crm_config.py` — CRMConfig, CRMFieldDef, CRMConfigLoader, ConfigValidationError, CredentialResolutionError
- [x] 1.3 RED: `backend/tests/unit/integrations/test_field_mapping.py` — 17 tests covering all coercion types, required/optional, purity
- [x] 1.4 GREEN/REFACTOR: `backend/app/integrations/field_mapping.py` + `backend/app/integrations/__init__.py` — FieldMapper, MappingError, normalize_phone_e164, pure coercers
- [x] 1.5 REVIEW FIX: tightened unsafe coercion paths found by fresh review — unknown field types, non-E.164 phones, malformed dates, bool/int confusion, malformed YAML wrapping, required match_field, spec-name aliases, field_map/field_mapping aliases

## Completed Tasks (PR 2 — Airtable Adapter + CRM Sync Service)

- [x] 2.1 RED: `backend/tests/unit/integrations/test_airtable_adapter.py` — 12 tests covering CRMPort abstraction, create/update upsert paths, idempotency, 429 retry, 5xx retry, 3-failure exhaustion with structured log, non-retryable 4xx fast-fail, write-only contract
- [x] 2.2 GREEN: `backend/app/integrations/crm_port.py` — CRMPort ABC (upsert_record + health_check); `backend/app/integrations/adapters/__init__.py` — adapters package; `backend/app/integrations/adapters/airtable.py` — AirtableAdapter(CRMPort), AirtableUpsertError, make_adapter() factory, _compute_backoff() pure helper
- [x] 2.3 RED: `backend/tests/integration/integrations/test_crm_sync_service.py` — 7 tests covering DB lead → mapped upsert, match_field propagation, missing crm.yaml no-op, unknown lead_id no-op, CredentialResolutionError isolation, AirtableUpsertError isolation, write-only contract
- [x] 2.4 GREEN/REFACTOR: `backend/app/integrations/crm_sync_service.py` — async `sync_lead(client_id, lead_id, db_session)`, full error isolation, _lead_to_dict() pure helper
- [x] 2.5 REVIEW FIX (judgment-day): resolved 8 confirmed review issues on the Work Unit 2 diff — see "Review Fixes (PR 2)" below

## Completed Tasks (PR 3 — Summarizer Hook + Quintana Sandbox)

- [x] 3.1 RED: Extended `backend/tests/unit/test_summarizer.py` — 4 new tests covering:
  - `_schedule_crm_sync` schedules exactly one asyncio task (fire-and-forget, CS-1/CS-2)
  - `_schedule_crm_sync` NOT called when savepoint fails (CS-1)
  - `_schedule_crm_sync` no-op when crm.yaml missing (FM-4) — delegates to sync_lead
  - CRM task failure does not affect summarizer output (CS-5)
- [x] 3.2 GREEN: Modified `backend/app/summarizer.py` — added `_schedule_crm_sync()` generic dispatcher + wired after savepoint in `_run_summarizer()`
- [x] 3.3 RED/GREEN: Created `backend/clients/quintana-seguros/crm.yaml` sandbox config + `backend/tests/unit/integrations/test_quintana_sandbox.py` — 6 tests proving no Quintana-specific logic in `app/integrations/`, file existence, valid load, required fields, no hardcoded secrets, env-var-name-only api_key_env

## Pending Tasks (PR 4 / verification)

- [ ] 4.1 Focused pytest on integrations + summarizer
- [ ] 4.2 Full `cd backend && pytest` pre-handoff

---

## TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1 | `tests/unit/integrations/test_crm_config.py` | Unit | N/A (new files) | ✅ Written (9 tests referencing non-existent module) | ✅ 9/9 passed initially; ✅ 12 config tests after review fixes | ✅ Valid load, secret not in dict, missing file, missing required fields, missing env at resolve, arbitrary field types, unknown type rejection, malformed YAML wrapping | ✅ Removed dead `_VALID_FIELD_TYPES` constant; added `Field(default_factory=list)` |
| 1.2 | `tests/unit/integrations/test_crm_config.py` | Unit | N/A (new files) | ✅ Written first (module didn't exist) | ✅ 12/12 config tests passed after review fixes | ✅ Covered by test_crm_config.py | ✅ Safe validation/error wrapping |
| 1.3 | `tests/unit/integrations/test_field_mapping.py` | Unit | N/A (new files) | ✅ Written (17 tests referencing non-existent module), then 9 review-fix RED tests added | ✅ 26/26 mapping tests passed after review fixes | ✅ String, int, bool, date, phone E.164, required/optional, arbitrary map, purity, unsafe coercion rejection | ✅ Coercers remain pure; no network/DB coupling |
| 1.4 | `tests/unit/integrations/test_field_mapping.py` | Unit | N/A (new files) | ✅ Written first (module didn't exist) | ✅ 26/26 mapping tests passed after review fixes | ✅ Covered by test_field_mapping.py | ✅ Unknown type fallback removed |
| 1.5 | `tests/unit/integrations/` | Unit | ✅ Focused integrations suite | ✅ Fresh review identified missing failure-path tests | ✅ `pytest tests/unit/integrations/ -q` → 43 passed | ✅ Review issues covered: unknown type, malformed YAML, invalid date, bool/int confusion, non-E.164 phone, required match_field, spec alias compatibility, fractional float rejection, field_map alias compatibility | ✅ Safer fail-fast semantics |
| 2.1 | `tests/unit/integrations/test_airtable_adapter.py` | Unit | N/A (new files) | ✅ Written (12 tests referencing non-existent modules) | ✅ 12/12 passed after GREEN implementation | ✅ Create path, update path, idempotent double-call, 429 retry, 5xx retry, exhaustion, non-retryable 4xx, write-only | ✅ Extracted _compute_backoff() as pure helper; _do_upsert() separated from retry wrapper |
| 2.2 | `tests/unit/integrations/test_airtable_adapter.py` | Unit | N/A (new files) | ✅ Written first (modules didn't exist) | ✅ 12/12 passed | ✅ Covered by test_airtable_adapter.py | ✅ make_adapter factory; base_id at construction time; _get_table patchable |
| 2.3 | `tests/integration/integrations/test_crm_sync_service.py` | Integration | N/A (new files) | ✅ Written (7 tests referencing non-existent module) | ✅ 7/7 passed after fixture fix (Client.voice_id required) | ✅ Success path, match_field propagation, no-crm.yaml noop, unknown lead noop, credential error isolation, adapter error isolation, write-only | ✅ _seed_test_client() helper for DB setup |
| 2.4 | `tests/integration/integrations/test_crm_sync_service.py` | Integration | N/A (new files) | ✅ Written first (module didn't exist) | ✅ 7/7 passed | ✅ Covered by test_crm_sync_service.py | ✅ _lead_to_dict() extracted as pure helper; error handlers explicit and non-re-raising |
| 3.1 | `tests/unit/test_summarizer.py` | Unit | ✅ 70/70 pre-existing tests passing | ✅ 4 tests written referencing non-existent `_schedule_crm_sync` — all 4 FAILED (ImportError / AttributeError) | ✅ 4/4 passed after GREEN implementation; full suite 74/74 | ✅ 2 test cases per behavior: (a) schedule called / (b) not called on failure; (a) no-op client / (b) crm-configured client | ✅ Implementation already clean; function docstring explains generic-dispatcher role |
| 3.2 | `tests/unit/test_summarizer.py` | Unit | ✅ 70/70 baseline confirmed before modifying summarizer.py | ✅ Tests written first (GREEN target was 4 failing tests) | ✅ 74/74 full summarizer suite green | ✅ Covered by 4 test scenarios in task 3.1 | ✅ Lazy import inside function; no top-level coupling to crm_sync_service |
| 3.3 | `tests/unit/integrations/test_quintana_sandbox.py` | Unit | N/A (new test file) | ✅ 4/6 tests FAILED (crm.yaml missing); 1 passed (no-quintana-in-integrations); 1 skipped | ✅ 6/6 passed after crm.yaml created | ✅ Triangulated: existence check, full load, required fields (6 assertions), no-secret, env-var-name format, no-quintana-in-code | ✅ crm.yaml uses only safe sandbox placeholders and env var names |

## Test Summary

- **Total tests written (PR 1)**: 43 (unit integrations)
- **Total tests written (PR 2)**: 19 (12 unit adapter + 7 integration sync service)
- **Total tests written (PR 3)**: 10 (4 summarizer hook + 6 Quintana sandbox)
- **Cumulative new tests**: 72
- **Baseline before PR 1**: 1831 tests passing
- **After PR 1**: 1874 tests (43 new)
- **After PR 2**: 1897 tests (19 new + 4 review-fix tests; full suite confirmed)
- **After PR 3**: 1907 tests (10 new) — full suite confirmed: `1907 passed, 0 failures`
- **Regressions**: 0
- **Layers used**: Unit (65), Integration (7)
- **Approval tests** (refactoring): None — no refactoring tasks in any PR
- **Pure functions created (PR 1)**: `normalize_phone_e164`, `_coerce_string`, `_coerce_integer`, `_coerce_boolean`, `_coerce_date`, `_coerce_phone`, `FieldMapper.map`
- **Pure functions created (PR 2)**: `_compute_backoff`, `_lead_to_dict`
- **Pure functions created (PR 3)**: None — `_schedule_crm_sync` is a dispatcher (schedules async task; no pure logic to extract)
- **Discoveries (PR 3)**: `asyncio.create_task` cannot be patched inside an async context using simple monkeypatch — must use `unittest.mock.patch("asyncio.create_task", ...)` directly. The fire-and-forget pattern means the coroutine is not awaited inside `_schedule_crm_sync`; tests verify `mock_sync.await_count == 0` to confirm this.

---

## Files Changed

### PR 1 Files
| File | Action | Description |
|------|--------|-------------|
| `backend/app/integrations/__init__.py` | Created | Package init |
| `backend/app/integrations/crm_config.py` | Created | CRMConfig, CRMFieldDef Pydantic models; CRMConfigLoader.load(); ConfigValidationError, CredentialResolutionError |
| `backend/app/integrations/field_mapping.py` | Created | FieldMapper.map() pure transform; type coercers; normalize_phone_e164; MappingError |
| `backend/tests/unit/integrations/__init__.py` | Created | Test package init |
| `backend/tests/unit/integrations/test_crm_config.py` | Created | 15 unit tests for CRM config loader and unsafe config failure paths |
| `backend/tests/unit/integrations/test_field_mapping.py` | Created | 28 unit tests for field mapping coercion and unsafe mapping failure paths |
| `backend/pyproject.toml` | Modified | Added `pyyaml>=6.0` to explicit dependencies |
| `.sdd/airtable-crm-integration/tasks.md` | Modified | Marked tasks 1.1–1.4 as [x] complete |

### PR 2 Files
| File | Action | Description |
|------|--------|-------------|
| `backend/app/integrations/crm_port.py` | Created | CRMPort ABC — upsert_record() abstract method + health_check() default |
| `backend/app/integrations/adapters/__init__.py` | Created | Adapters sub-package init |
| `backend/app/integrations/adapters/airtable.py` | Created | AirtableAdapter(CRMPort) — upsert with 3-attempt retry + exponential backoff + jitter; AirtableUpsertError; make_adapter() factory; _compute_backoff() pure helper |
| `backend/app/integrations/crm_sync_service.py` | Created | async sync_lead(client_id, lead_id, db_session) — full orchestration with error isolation; _lead_to_dict() pure helper |
| `backend/tests/unit/integrations/test_airtable_adapter.py` | Created | 12 unit tests for adapter create/update paths, retry, exhaustion, non-retryable errors, write-only contract |
| `backend/tests/integration/integrations/__init__.py` | Created | Integration test package init |
| `backend/tests/integration/integrations/test_crm_sync_service.py` | Created | 10 integration tests for sync_lead orchestration (incl. cross-client guard + factory-error isolation) |
| `backend/pyproject.toml` | Modified | Added `pyairtable>=2.3.0` runtime dependency |
| `backend/uv.lock` | Created/Modified | Lockfile incl. pyairtable 3.3.0 |
| `.sdd/airtable-crm-integration/tasks.md` | Modified | Marked tasks 2.1–2.4 as [x] complete |

### PR 2 Review-Fix Files (judgment-day)
| File | Action | Description |
|------|--------|-------------|
| `backend/app/integrations/adapters/airtable.py` | Modified | Write-side `batch_upsert` (no reads); `asyncio.to_thread` boundary; `_extract_status_code()` + `_extract_record_id()` helpers; HTTP-client-agnostic retry |
| `backend/app/integrations/crm_sync_service.py` | Modified | Cross-tenant ownership guard; outer catch-all error isolation |
| `backend/tests/unit/integrations/test_airtable_adapter.py` | Modified | Rewrote upsert tests for batch_upsert; no-read-API enforcement; pyairtable-style retry test |
| `backend/tests/integration/integrations/test_crm_sync_service.py` | Modified | Added cross-client mismatch, matching-client control, factory-error isolation tests |

### PR 3 Files
| File | Action | Description |
|------|--------|-------------|
| `backend/app/summarizer.py` | Modified | Added `_schedule_crm_sync()` generic dispatcher function; wired call after savepoint in `_run_summarizer()` |
| `backend/clients/quintana-seguros/crm.yaml` | Created | Quintana sandbox CRM config — sandbox base_id/table_id placeholders; `api_key_env: QUINTANA_AIRTABLE_API_KEY`; 10 field mappings |
| `backend/tests/unit/test_summarizer.py` | Modified | Added 4 TDD tests for `_schedule_crm_sync` hook behavior (CS-1, CS-2, FM-4, CS-5) |
| `backend/tests/unit/integrations/test_quintana_sandbox.py` | Created | 6 structural tests: crm.yaml exists, loads valid, required fields, no secrets, no quintana-in-integrations, env-var-name format |
| `.sdd/airtable-crm-integration/tasks.md` | Modified | Marked tasks 3.1–3.3 as [x] complete |

---

## Review Fixes (PR 2 — judgment-day surgical pass)

Eight confirmed review issues on the uncommitted Work Unit 2 diff (adapter + sync service only). Scope held to those two modules plus their tests and `pyproject.toml`/`uv.lock`.

| # | Issue | Fix | Evidence |
|---|-------|-----|----------|
| 1 | `_do_upsert()` violated no-live-read (used `table.all(formula=...)`) | Replaced with write-side `Table.batch_upsert([{"fields": payload}], key_fields=[match_field])` — Airtable resolves the dedup match server-side in a single write request. No list/all/find/get. | `app/integrations/adapters/airtable.py` `_do_upsert`; `_extract_record_id()` parses `UpsertResultDict` |
| 2 | async `upsert_record` called sync pyairtable network methods directly (blocks event loop) | Wrapped the blocking `batch_upsert` call in `asyncio.to_thread(...)` | `_do_upsert` |
| 3 | pyairtable was a runtime dependency but undeclared | Added `pyairtable>=2.3.0` to `[project].dependencies`; regenerated `uv.lock` (resolves pyairtable 3.3.0) | `backend/pyproject.toml`, `backend/uv.lock` |
| 4 | Cross-tenant leakage: `sync_lead` fetched lead by id only | Added tenant guard — skip + warn if `lead.client_id != client_id` before any CRM call | `crm_sync_service.py` step 3b |
| 5 | Retry caught only `httpx.HTTPStatusError`; pyairtable raises `requests.HTTPError` | Retry now inspects any exception via `_extract_status_code()` (reads `response.status_code` or `status_code`); decoupled from any HTTP client / pyairtable import | `airtable.py` `_extract_status_code`, retry loop |
| 6 | Formula-construction warning | Eliminated — no read formula is constructed anymore | n/a (code removed) |
| 7 | Unexpected loader/factory/pre-upsert failures could propagate | Wrapped full orchestration body in an outer `try/except Exception` catch-all that logs and swallows; known modes still get specific structured logs | `crm_sync_service.py` outer guard |
| 8 | Tests did not enforce no-read-API or cross-client behavior | Adapter tests assert `all/first/get/iterate/create/update` never called and only `batch_upsert` used; added pyairtable-style retry test; integration adds cross-client mismatch (no upsert), matching-client control, and factory-error isolation tests | `test_airtable_adapter.py`, `test_crm_sync_service.py` |

### Review-fix test evidence
- Focused: `pytest tests/unit/integrations/ tests/integration/integrations/ -q` → **66 passed** (was 62; +4 new tests).
- Full: `pytest tests/ -q` → **1897 passed**, 0 regressions (was 1893).
- New tests: `test_upsert_retries_on_pyairtable_style_exception`, `test_upsert_does_not_call_any_read_method` (hardened), `test_sync_lead_cross_client_mismatch_does_not_upsert`, `test_sync_lead_matching_client_does_upsert`, `test_sync_lead_factory_error_is_swallowed`.
- Discovery: pyairtable 3.x keeps the positional `Table(api_key, base_id, table_id)` constructor and `batch_upsert(records, key_fields=...)` → `UpsertResultDict` shape — production `_get_table()` needs no change.

---

## Deviations from Design

### PR 1
1. **`CRMFieldDef.model_config = {"extra": "forbid"}`** vs design's implied permissive model: Added `extra="forbid"` on `CRMFieldDef` to catch typos in crm.yaml field definitions early. `CRMConfig` uses `extra="ignore"` to allow future YAML keys without breaking load.
2. **Canonical names + spec aliases**: The implementation uses `provider`, `api_key_env`, and `field_mappings` internally while accepting spec/back-compat aliases `adapter`, `credentials_key`, `field_map`, and `field_mapping` at YAML load time.
3. **`_DEFAULT_CLIENTS_ROOT` path**: Computed as `Path(__file__).parent.parent.parent / "clients"` — resolves to `backend/clients/` at runtime, matching the project layout.

### PR 2
1. **`AirtableAdapter.__init__` takes `base_id`**: Design showed adapter constructed via `make_adapter(provider, api_key)`. Implementation adds `base_id` as second construction argument so `_get_table()` can construct pyairtable `Table(api_key, base_id, table_id)` without needing base_id at call time. This is more explicit than injecting it per-call and keeps the adapter stateless per request.
2. **`sync_lead` takes `db_session` as argument**: Design's data flow shows it reading from SQLite; explicit session injection makes the function fully testable (matches existing service layer patterns like `create_lead(session, ...)`).
3. **AirtableUpsertError raised (not swallowed) in adapter**: The adapter raises `AirtableUpsertError` after exhaustion (CS-5 says the caller must not propagate). `crm_sync_service` catches it. This matches the layering principle: adapter knows about retry failures; sync service knows about isolation.
4. **Non-retryable 4xx errors fail immediately**: Design says "retry on transient failure with exponential backoff + jitter, up to 3 attempts" (CS-4). 429/5xx = retryable; 4xx (403, 422) = non-retryable per RFC semantics. Added explicit fast-fail for non-retryable status codes.

### PR 3
1. **`_schedule_crm_sync` is `async def`**: The function uses lazy import (`from app.integrations import crm_sync_service`) inside its body to avoid circular import risk. An `async def` with no `await` is slightly unusual but consistent with `_auto_schedule_if_needed` pattern and allows future `await` use if needed. Fire-and-forget is achieved via `asyncio.create_task()`, not by awaiting the coroutine.
2. **`_schedule_crm_sync` does NOT check crm.yaml before scheduling**: Design says "generic dispatcher". The no-op behavior is entirely inside `sync_lead()` (returns if no config). This keeps the summarizer decoupled from any CRM config knowledge — the hook schedules unconditionally, `sync_lead` handles the no-op.

---

## Workload / PR Boundary

- **PR 1 (done)**: Config + field mapping foundation — ~180 lines prod + ~290 lines tests = ~470 lines
- **PR 2 (done)**: Airtable adapter + sync service — ~185 lines prod + ~220 lines tests = ~405 lines + judgment-day fixes
- **PR 3 (this batch)**: Summarizer hook + Quintana sandbox — ~50 lines prod + ~200 lines tests = ~250 lines (well within 400-line budget)
- **Mode**: Chained PR slice (stacked-to-main)
- **Current work unit**: Unit 3 — Summarizer hook + Quintana sandbox crm.yaml
- **Boundary**: PR 3 depends on PR 2 (crm_sync_service.sync_lead). No admin UI. No live Airtable reads. No production credentials.
- **Chain**: This is the final implementation PR. PR 4 = verification pass (tasks 4.1–4.2).

---

## Status

11/14 tasks complete (PR 1 + PR 2 + PR 3 done). Full suite: **1907 passed, 0 regressions**. PR 3 batch is ready for orchestrator review. Tasks 4.1–4.2 (verification/cleanup pass) remain — these can run in the verify phase or as a final cleanup before handoff.
