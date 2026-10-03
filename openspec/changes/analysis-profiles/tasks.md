# Tasks: Qora Config Phase 5 — Analysis Profiles

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~1,700 total across 6 units |
| 800-line budget risk | High if combined; Low per-unit when kept separate |
| 400-line budget risk | Low — every unit estimated at or under ~400 lines |
| Chained PRs recommended | Yes — six review slices, strictly ordered |
| Suggested split | One PR per numbered task below; task 3 (per-call catalog injection) is never combined with any other task |
| Delivery strategy | auto-forecast |
| Chain strategy | stacked-to-main |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Templates + schema + migration 0023 | PR 1 | Additive; seeds every existing client. Rollback: `alembic downgrade -1`; remove new files. |
| 2 | Profile service + API | PR 2 | Additive; depends on PR 1. Rollback: revert PR. |
| 3 | Per-call catalog injection in interests.py/pipeline.py + skip-when-empty + summarizer stamping | PR 3 | Behavioral cutover — never combined with another task. Depends on PR 1-2. Rollback: revert PR. |
| 4 | leads/router.py + calls/router.py consumer cutover | PR 4 | Depends on PR 3. Rollback: revert PR. |
| 5 | frontend dimension-labels.ts cutover | PR 5 | Depends on PR 2 only (API existing). Rollback: revert PR. |
| 6 | Full suites + golden regression + rollout notes | PR 6 | Depends on all prior tasks. Rollback: n/a — verification only. |

## Known Environmental Failures

None identified at the time of writing — this change's own test additions are the only expected RED states before implementation. If the base backend or frontend suite has pre-existing unrelated failures at apply time, they must be named explicitly here before any task reports `status: completed`.

## Phase 1: Templates + Schema + Migration 0023

- [ ] 1.1 Create `backend/app/analysis/profiles/schema.py` with `ProductEntry`, `NeedTagEntry`, `AnalysisProfileConfigV1`.
      RED: `test_product_entry_rejects_empty_label`, `test_need_tag_entry_rejects_empty_label`, `test_analysis_profile_config_defaults_to_empty_lists` (new file `backend/tests/unit/analysis/profiles/test_schema.py`) — fail (module doesn't exist).
      GREEN: validation errors fire exactly as named; a config with no `products`/`need_tags` passed defaults to empty lists, not a validation error.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/analysis/profiles/test_schema.py`
      Rollback: delete the file; revert commit.

- [ ] 1.2 Create `backend/app/analysis/profiles/templates.py` with `insurance` and `generic` `ProfileTemplate` constants; `insurance` sourced from `catalog.py`'s live `PRODUCT_CATALOG`/`NEED_TAGS` plus `dimension-labels.ts`'s existing label text.
      RED: `test_insurance_template_matches_catalog_ids_exactly`, `test_generic_template_is_empty` (new file `backend/tests/unit/analysis/profiles/test_templates.py`) — fail (module doesn't exist).
      GREEN: `insurance.config.products`' ids as a set equal `set(PRODUCT_CATALOG)`; `insurance.config.need_tags`' ids as a set equal `set(NEED_TAGS)`; `generic.config.products == []` and `generic.config.need_tags == []`.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/analysis/profiles/test_templates.py`
      Rollback: delete the file; revert commit.

- [ ] 1.3 Add `ClientAnalysisProfileRevision` model to `backend/app/tenants/models.py`; `Client.active_analysis_profile_revision_id` FK; `CallAnalysis.analysis_profile_revision_id` (nullable) to `backend/app/calls/models.py`.
      RED: `test_client_analysis_profile_revision_model_fields_exist`, `test_client_has_active_analysis_profile_revision_fk`, `test_call_analysis_has_analysis_profile_revision_id` (new file `backend/tests/unit/tenants/test_analysis_profile_models.py`) — fail (fields don't exist).
      GREEN: all three fields import successfully; `unique(client_id, revision_number)` constraint present via model metadata.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/tenants/test_analysis_profile_models.py`
      Rollback: delete the model fields; revert commit.

- [ ] 1.4 Create `backend/alembic/versions/20261003_0023_analysis_profiles_schema.py` (chained after `20261003_0022_import_crm_yaml_integrations.py`): `CREATE TABLE client_analysis_profile_revisions`; add the two new FK columns; seed revision 1 for every existing client (Quintana = inline `insurance` data matching `catalog.py`'s literal IDs, everyone else = inline `generic` data — no `app.*` import, house pattern).
      RED: `test_analysis_profiles_schema_migration_creates_tables_and_seeds_every_client` — fails against a tmp DB at the current head (table doesn't exist, no seeded rows).
      GREEN: `alembic upgrade head` on a tmp DB creates the table with expected columns/constraints (`PRAGMA table_info`/`PRAGMA index_list`); every existing `clients` row has exactly one seeded revision; Quintana's seeded revision's product/need-tag ids exactly match `catalog.py`'s live constants; every other client's seeded revision has empty `products`/`need_tags`.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/test_alembic_tooling.py -k analysis_profiles_schema`
      Rollback: `alembic downgrade -1` on the tmp DB; remove the revision file.

## Phase 2: Profile Service + API

- [ ] 2.1 Create `backend/app/analysis/profiles/service.py`: `resolve_client_catalog(session, client_id)`, `create_revision`/`get_revision`/`list_revisions`/`rollback`/`apply_template`, all built on `revisions_service.py`'s existing generic private helpers parameterized for `ClientAnalysisProfileRevision`.
      RED: `test_resolve_client_catalog_returns_active_revision_config`, `test_create_revision_does_not_mutate_existing_rows`, `test_rollback_creates_new_revision_not_resurrection`, `test_apply_template_creates_revision_from_code_data` (new file `backend/tests/unit/analysis/profiles/test_service.py`) — fail (module doesn't exist).
      GREEN: all four scenarios behave exactly as named; `rollback` to revision 1 when the client is on revision 2 creates revision 3 (not reactivating revision 1's row), and `active_analysis_profile_revision_id` points at revision 3 afterward.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/analysis/profiles/test_service.py`
      Rollback: delete the file; revert commit.

- [ ] 2.2 Add `PUT /clients/{client_id}/analysis-profile` write validation: unique product ids, unique need-tag ids, every `label_es`/`label_en` non-empty.
      RED: `test_put_profile_rejects_duplicate_product_id`, `test_put_profile_rejects_duplicate_need_tag_id`, `test_put_profile_rejects_empty_label` (new file `backend/tests/unit/analysis/profiles/test_router.py`) — fail (endpoint doesn't exist, 404).
      GREEN: all three scenarios return 422 with the exact offending field named; a valid submission creates a new revision and returns its config.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/analysis/profiles/test_router.py -k put_profile`
      Rollback: remove the route handler; revert commit.

- [ ] 2.3 Add `GET /clients/{client_id}/analysis-profile`, `GET .../analysis-profile/revisions`, `POST .../analysis-profile/rollback`, `POST .../analysis-profile/apply-template`.
      RED: `test_get_profile_returns_active_revision`, `test_get_revisions_lists_all_in_order`, `test_post_rollback_requires_target_in_same_client`, `test_post_apply_template_requires_known_vertical` — fail (endpoints don't exist).
      GREEN: all four scenarios behave exactly as named; a rollback target belonging to a different client returns 404 (same tenant-scoping precedent as every prior revisions router); an unknown `vertical` value returns 422.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/analysis/profiles/test_router.py`
      Rollback: remove the route handlers; revert commit.

## Phase 3: Per-Call Catalog Injection (do not combine with other tasks)

- [ ] 3.1 Move `interests.py`'s `_build_prompt`/`DIMENSION["prompt"]` off module-load construction to a per-call function taking the resolved catalog as a parameter.
      RED: `test_build_prompt_differs_for_different_catalogs_in_same_process` (extends `backend/tests/unit/analysis/universal/interest/test_interests.py`) — fails against the unmodified source (prompt is fixed at import time, identical regardless of any runtime catalog).
      GREEN: calling the per-call build function with two different `AnalysisProfileConfigV1` catalogs in the same test process produces two different prompt strings; the `insurance` catalog's prompt text matches today's pre-change `DIMENSION["prompt"]` exactly (string equality) — the literal module-load-removal regression proof.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/analysis/universal/interest/test_interests.py`
      Rollback: revert the file; prompt construction reverts to module-load against `catalog.py`'s constants directly.

- [ ] 3.2 Thread the resolved catalog through `pipeline.run_interest_pipeline`; add the empty-products skip (P5-D5).
      RED: `test_run_interest_pipeline_skips_both_agents_when_products_empty`, `test_run_interest_pipeline_runs_agent_1_when_needs_empty_but_products_not` (extends `backend/tests/unit/analysis/universal/interest/test_pipeline.py`) — fail (pipeline doesn't accept a catalog parameter yet; no skip logic exists).
      GREEN: an empty-products catalog results in zero calls to the OpenAI client (assert via a call-count mock) and a normal (not error-marker) empty `InterestsAxis(items=[])` result; a non-empty-products/empty-need-tags catalog still invokes Agent 1.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/analysis/universal/interest/test_pipeline.py`
      Rollback: revert the file; pipeline reverts to always calling both agents against the module-level catalog.

- [ ] 3.3 `summarizer.py` calls `resolve_client_catalog`, passes it into the pipeline, stamps `ca.analysis_profile_revision_id` on the written `CallAnalysis` row.
      RED: `test_summarizer_stamps_analysis_profile_revision_id`, `test_summarizer_later_edit_does_not_change_earlier_call_stamp` (extends `backend/tests/unit/test_summarizer.py`) — fail against the unmodified source (column is never set, and doesn't exist until task 1.3's migration).
      GREEN: a newly analyzed call's `CallAnalysis.analysis_profile_revision_id` equals the client's active revision id at analysis time; editing the client's profile AFTER that call was analyzed does not change the already-written row's stamped id (P5-D6's historical-interpretability proof).
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/test_summarizer.py -k analysis_profile`
      Rollback: revert the file; no stamping occurs, column stays `NULL` for all new rows (functionally degraded, not broken — rollback is safe).

- [ ] 3.4 Golden regression: Quintana's resolved catalog and resulting Agent-1 prompt are byte-identical to pre-change behavior.
      RED: `test_quintana_catalog_and_prompt_are_byte_identical_to_pre_change` (new file `backend/tests/regression/test_analysis_profiles_golden.py`) — fails until 3.1-3.3 land (no resolved-catalog path exists yet to compare against).
      GREEN: seed Quintana via migration 0023, call `resolve_client_catalog`, assert product/need-tag id sets exactly equal `catalog.py`'s live constants; build the per-call prompt from that resolved catalog for a fixed transcript/language input and assert it string-equals the pre-change module-level `DIMENSION["prompt"]` value for the same inputs.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/regression/test_analysis_profiles_golden.py`
      Rollback: n/a — regression gate; a failure here blocks task 3 from being considered done, it does not require reverting unrelated code.

## Phase 4: leads/router.py + calls/router.py Consumer Cutover

- [ ] 4.1 Cut over `leads/router.py`'s interest rollup (lines 544-628) to read the resolved catalog via `resolve_client_catalog` instead of importing `PRODUCT_CATALOG`/`NEED_TAGS` directly.
      RED: existing `backend/tests/.../test_leads_router.py` interest-rollup tests — adjusted to seed a `client_analysis_profile_revisions` row instead of relying on the module-level constants; fail against the unmodified source (still importing the constants directly).
      GREEN: the same tests pass filtering by the resolved catalog; a second client with a different (e.g. `generic`) catalog produces a correspondingly different rollup in the same test run, proving the filter is no longer globally fixed.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/leads/test_leads_router.py -k interest`
      Rollback: revert the file; rollup reverts to importing `PRODUCT_CATALOG`/`NEED_TAGS` directly.

- [ ] 4.2 Cut over `calls/router.py`'s `CallAnalysisResponse` building (line ~695 area) to read the resolved catalog for any label resolution it performs.
      RED/GREEN: same pattern as 4.1, against `test_calls_router.py`'s existing analysis-response tests.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/calls/test_calls_router.py -k analysis`
      Rollback: same pattern as 4.1.

- [ ] 4.3 Static-import regression guard: no remaining direct `PRODUCT_CATALOG`/`NEED_TAGS` import in `leads/router.py` or `calls/router.py`.
      RED: `test_no_remaining_direct_catalog_import_in_consumers` (new file `backend/tests/unit/test_catalog_consumer_imports_removed.py`) — fails until 4.1-4.2 are both complete.
      GREEN: a source-grep-based test over both files finds zero matches for a direct `from app.analysis.universal.interest.catalog import` statement.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/test_catalog_consumer_imports_removed.py`
      Rollback: n/a — verification-only guard; a failure means a consumer was missed, not that this task needs reverting.

## Phase 5: Frontend dimension-labels.ts Cutover

- [ ] 5.1 Modify `dimension-labels.ts`'s lookup function to fetch `GET /clients/{client_id}/analysis-profile` first, falling back to the existing static map (lines 144-160 and the rest of the product/need-tag entries) when the fetch fails or a specific id is missing from the fetched profile; log a console warning on fallback.
      RED: `test_label_lookup_uses_fetched_profile_when_available`, `test_label_lookup_falls_back_to_static_map_on_fetch_failure`, `test_fallback_logs_console_warning` (new file `frontend/src/config/dimension-labels.test.ts`) — fail against the unmodified source (no fetch path exists at all).
      GREEN: a mocked successful fetch returning a label for a given product id is used in preference to the static map; a mocked failed fetch (or a missing id) falls back to the static map and triggers exactly one console warning.
      Check: `cd frontend && npm test -- dimension-labels`
      Rollback: revert the file; lookup reverts to the static-only map.

- [ ] 5.2 Confirm `analysis-panel.tsx`'s chip rendering is unaffected — it already reads through `dimension-labels.ts`'s lookup function with no direct import of the static map itself.
      RED: n/a — verification task, not a behavioral change.
      GREEN: existing `analysis-panel.tsx` component tests pass unmodified against the new lookup-function implementation underneath.
      Check: `cd frontend && npm test -- analysis-panel`
      Rollback: n/a — verification only.

## Phase 6: Full Suites + Golden Regression + Rollout Notes

- [ ] 6.1 Run the full backend suite.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider`
      Rollback: n/a — verification gate; any failure blocks closing the change until fixed or explicitly triaged as pre-existing/unrelated.

- [ ] 6.2 Run the full frontend suite.
      Check: `cd frontend && npm test`
      Rollback: n/a — verification gate, same as 6.1.

- [ ] 6.3 Re-run the golden regression test (task 3.4) one final time after tasks 4-5 land, confirming Quintana's catalog/prompt equivalence still holds end-to-end.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/regression/test_analysis_profiles_golden.py`
      Rollback: n/a — verification gate.

- [ ] 6.4 Document the rollout: note that no production env var or manual operator action is required (migration 0023 is self-contained and additive); the admin editor UI for profile editing is explicitly deferred to the user's own later work, not this change.
      Check: rollout notes added to this file or a follow-up PR description — no executable check.
      Rollback: n/a — documentation only.
