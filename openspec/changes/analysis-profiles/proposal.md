# Proposal: Qora Config Phase 5 — Analysis Profiles

## Intent

Today, the universal post-call interest-detection pipeline is not universal at all: `backend/app/analysis/universal/interest/catalog.py` hardcodes `PRODUCT_CATALOG` (9 insurance products) and `NEED_TAGS` (10 need tags) as module-level `list[str]` constants — Quintana Seguros's own product line, baked into a module every client's calls run through. Worse, `interests.py` builds Agent 1's full prompt (`_PROMPT_BODY`, `DIMENSION["prompt"]`) **at module import time**, injecting the catalog once for the lifetime of the process — there is no per-call, let alone per-client, hook at all. The catalog module's own docstring (`catalog.py:5-14`) already names the intended seam — `get_product_catalog(client_id)` / `get_need_tags(client_id)` — but nothing implements it.

This hardcoding is survey critical finding #5. Every non-insurance client either sees insurance product IDs in their `detected_interests`/`CallAnalysis.products` data, or — more likely, since nobody has configured a second vertical yet — the interest pipeline silently produces meaningless output for them. Three consumers compound the blast radius: `leads/router.py`'s lead-interest rollup filters by the hardcoded `PRODUCT_CATALOG`/`NEED_TAGS` sets, `calls/router.py`'s `CallAnalysisResponse` passes `products`/`specific_needs` through verbatim, and the frontend (`dimension-labels.ts`, `analysis-panel.tsx`) hardcodes Spanish/English labels per product ID with no API-driven source.

Phase 1b (`agent-config-inheritance`) already named this as explicitly out of scope ("Analysis profiles — phase P5") and its `FIELD_POLICY` model is scalar-only — a catalog is a list of structured records (id + two labels), which does not fit that resolver's shape. This phase gives every client a first-class, versioned **analysis profile**: the product catalog and need-tag catalog (with Spanish/English labels), decoupled from the rule engine (next-action thresholds stay exactly where phase 1b/earlier phases left them — on `Client` columns, already API-editable) and decoupled from code.

## Scope

### In Scope

- Two new tables: `client_analysis_profile_revisions` (immutable, insert-only — the same revision pattern 1a/1b/P3 already use) storing `config` JSON (`schema_version`, `vertical`, `products: [{id, label_es, label_en, description}]`, `need_tags: [{id, label_es, label_en}]`), plus `source`/`created_by`/`created_at`/`note`; and `clients.active_analysis_profile_revision_id` pointing at the active one. Reuses the generic revision helpers already factored out in `backend/app/tenants/revisions_service.py` (`_create_revision`/`_get_revision`/`_list_revisions`/`_activate_revision`/`_rollback_to_revision`), the same reuse pattern `create_client_revision`/`create_agent_config_revision` already demonstrate for two different owner tables.
- Two code-only vertical templates in `backend/app/analysis/profiles/templates.py`: `insurance` (today's exact 9 product IDs + 10 need-tag IDs, byte-identical, with `label_es`/`label_en` sourced from the current `dimension-labels.ts` entries) and `generic` (empty catalog, empty need tags). Templates are Python data, not DB rows — applying one is an explicit API action that creates a new revision from it.
- Migration `20261003_0023` (chained after P3's `20261003_0022`, the current Alembic head) creates both tables and seeds revision 1 for every client: Quintana Seguros gets the `insurance` template (inline data in the migration, no `app.*` import — house pattern), every other client gets `generic`. This is a byte-identical golden-regression point for Quintana: before and after this migration, Quintana's resolved catalog is unchanged.
- Per-call, per-client catalog injection: `interests.py`'s Agent-1 prompt moves from module-load construction to a function built per call from the calling client's active profile; `pipeline.py` threads the client's catalog through Agent 1 and Agent 2.
- Empty-catalog short-circuit: when a client's active profile has an empty product catalog, the interest pipeline (`pipeline.py`) is skipped entirely for that call — no Agent 1/2 calls, `detected_interests` stays empty. Empty need tags are likewise skipped from the need-tag side of Agent 1's validation.
- `summarizer.py` stores the resolved `analysis_profile_revision_id` on the `CallAnalysis` row it writes, so a historical `products` JSON array stays interpretable against the exact catalog that was active when the call was analyzed, independent of later profile edits.
- `call_analyses.analysis_profile_revision_id` (nullable — existing rows predate this column) added via the same migration.
- API: `GET`/`PUT` a client's analysis profile (PUT validates unique product/need-tag ids and non-empty labels), `GET` revision history, `POST` rollback (creates a new revision copying an old one's config — never rewrites history), `POST apply-template {vertical}` (creates a new revision from a named template).
- Consumer cutover: `leads/router.py`'s interest rollup and `calls/router.py`'s response building read the calling client's resolved catalog (via the active profile) instead of importing the module-level `PRODUCT_CATALOG`/`NEED_TAGS` constants directly.
- Frontend: `dimension-labels.ts` reads product/need-tag labels from `GET` the client's analysis profile, falling back to today's static map when the API call fails or a label is missing — no editor UI, no redesign of `analysis-panel.tsx`'s chip rendering in this phase.

### Out of Scope

- Next-action rule thresholds (`next_action_max_attempts`, `next_action_min_interest_for_followup`, `next_action_close_on_hard_rejection`, the `scheduler_*` columns, `analysis_language`) — these stay exactly where they are today, on `Client` columns, already API-editable (P5-D1). This phase does not touch `ClientRules` or `summarizer.py`'s existing `ClientRules` construction (`summarizer.py:448-466`).
- The rule engine itself (`next_action.py`'s logic that consumes `ClientRules`) — unaffected; only the catalog the interest pipeline detects against changes, not the downstream rules that act on detected interests.
- CRM provider config/secrets (phase P3, already shipped) — unrelated config surface, no shared tables.
- The three-level Standard→Client→Agent inheritance resolver (phase 1b) — analysis profiles are a separate, independent revisioned config, not a `FIELD_POLICY`-governed scalar field; this phase does not fold the catalog into that resolver.
- An admin editor UI for building/editing a profile's product and need-tag lists — this phase ships API-only; the editor UI is explicitly owned by the user as a separate, later piece of work.
- Any other post-call analysis dimension (`objections`, `pain_points`, `service_issues`, `misc_notes`, etc.) — only the interest-detection dimension's catalog (products + need tags) is profile-driven; every other dimension's prompt/schema is unaffected.
- Dropping or rewriting `backend/app/analysis/universal/interest/catalog.py`'s existing `PRODUCT_CATALOG`/`NEED_TAGS` constants — they remain as the literal source of the `insurance` template's data and as a documented historical reference; nothing deletes them in this phase.

## Capabilities

> This section is the CONTRACT between proposal and specs phases.

### New Capabilities

- `analysis-profiles`: the `client_analysis_profile_revisions` table, its immutable revision lifecycle (reusing the generic revisions service), the `generic`/`insurance` code templates, the migration that seeds every existing client, the per-call/per-client catalog resolution replacing interests.py's module-load injection, the empty-catalog pipeline skip, the `analysis_profile_revision_id` stamped onto `CallAnalysis`, and the profile CRUD/rollback/apply-template API.

### Modified Capabilities

- None. `tenant-analysis` / next-action rule behavior (wherever it is currently specified, if at all) is unaffected — P5-D1 explicitly keeps thresholds on `Client` columns. No existing spec requirement is superseded by this change.

## Approach

**Templates and schema first, then the resolver, then the two pipeline call sites, then the consumers, then the frontend, then full-suite verification** — each layer additive until the interests.py/pipeline.py cutover task, matching the staged-rollout precedent already used in P3 and 1b.

1. Vertical templates (pure Python data) + the new model/schema + migration 0023 (seeds every client, Quintana = `insurance` byte-identical, everyone else = `generic`) — additive
2. Profile service (reusing the generic revisions helpers) + API (`GET`/`PUT`/`GET` revisions/`POST` rollback/`POST apply-template`) — additive, nothing in the hot path calls it yet
3. Per-call catalog injection: `interests.py`'s prompt moves off module load to a per-call build function; `pipeline.py` threads the client's catalog through Agent 1/2; empty-catalog skip; `summarizer.py` stamps `analysis_profile_revision_id` — the only behavioral cutover task, never combined with another task
4. Consumer cutover: `leads/router.py` and `calls/router.py` read the resolved catalog instead of the module-level constants
5. Frontend: `dimension-labels.ts` reads from `GET` profile with the existing static map as fallback
6. Full backend + frontend suites, golden regression test for Quintana (byte-identical catalog, byte-identical prompt text for a known fixture call), rollout notes

## Affected Areas

| Area | Impact | Description |
|------|--------|--------------|
| `backend/app/analysis/profiles/templates.py` (new) | New | `insurance` and `generic` vertical templates as Python data (`ProfileTemplate` shape) |
| `backend/app/analysis/profiles/schema.py` (new) | New | `AnalysisProfileConfigV1` Pydantic model: `schema_version`, `vertical`, `products: list[ProductEntry]`, `need_tags: list[NeedTagEntry]` |
| `backend/app/analysis/profiles/service.py` (new) | New | Profile CRUD built on the generic revisions helpers; `resolve_client_catalog(client_id) -> AnalysisProfileConfigV1` |
| `backend/app/analysis/profiles/router.py` (new) | New | `GET`/`PUT .../analysis-profile`, `GET .../analysis-profile/revisions`, `POST .../analysis-profile/rollback`, `POST .../analysis-profile/apply-template` |
| `backend/app/tenants/models.py` | Modified | New `ClientAnalysisProfileRevision` model; `Client.active_analysis_profile_revision_id` FK |
| `backend/app/calls/models.py` | Modified | `CallAnalysis.analysis_profile_revision_id` (nullable) |
| `backend/alembic/versions/20261003_0023_analysis_profiles_schema.py` (new) | New | `CREATE TABLE client_analysis_profile_revisions`; `clients.active_analysis_profile_revision_id`; `call_analyses.analysis_profile_revision_id`; seeds revision 1 for every existing client (Quintana = inline `insurance` data, everyone else = inline `generic` data — no `app.*` import, house pattern) |
| `backend/app/analysis/universal/interest/interests.py` | Modified | `_build_prompt`/`DIMENSION["prompt"]` move from module-load construction to a per-call function taking the client's resolved catalog as an argument |
| `backend/app/analysis/universal/interest/pipeline.py` | Modified | `run_interest_pipeline` threads the client's catalog through Agent 1/2; skips both agents entirely when the catalog is empty |
| `backend/app/summarizer.py` | Modified | Stamps `ca.analysis_profile_revision_id` on the `CallAnalysis` row it writes (alongside the existing `ClientRules` construction at lines 448-466, unchanged) |
| `backend/app/leads/router.py` | Modified | Lines 544-628 — interest rollup filters by the calling client's resolved catalog instead of the module-level `PRODUCT_CATALOG`/`NEED_TAGS` constants |
| `backend/app/calls/router.py` | Modified | Line ~695 area — `CallAnalysisResponse` building reads the calling client's catalog for any label resolution it needs (if any; data pass-through itself is unaffected) |
| `frontend/src/config/dimension-labels.ts` | Modified | Lines 144-160 and the rest of the product/need-tag label map become a fallback; labels are fetched from `GET .../analysis-profile` first |
| `frontend/src/features/leads/analysis-panel.tsx` | Unaffected (verify only) | Chip rendering reads from `dimension-labels.ts`'s existing lookup function — no change to this file's own code, confirmed in task 5/6 |

## Safety Model

1. **Quintana's behavior is byte-identical, provably** — the migration's inline `insurance` template data uses the exact same product/need-tag IDs as today's `catalog.py` constants; a golden regression test asserts the resolved catalog and the resulting Agent-1 prompt text for Quintana are unchanged before and after this change (P5-D4).
2. **Revisions are immutable, rollback is additive** — exactly like 1a/1b/P3's revision tables, no `UPDATE`/`DELETE` path exists on `client_analysis_profile_revisions`; a rollback creates a new revision copying an old one's config, never rewrites history.
3. **Empty catalog means no wasted LLM calls, not an error** — a `generic`-template client (every client but Quintana, today) has an empty product catalog; the interest pipeline recognizes this and skips Agent 1/2 entirely rather than running a pointless/degenerate LLM call against an empty allowlist (P5-D5).
4. **Historical data stays interpretable** — `call_analyses.analysis_profile_revision_id` means a `products` JSON array recorded two profile edits ago can still be resolved against the exact catalog that produced it, not against whatever the catalog looks like today (P5-D6).
5. **Rule engine is untouched** — this phase's safety model does not extend to next-action thresholds; those already have their own API-editable surface on `Client` columns (P5-D1) and this change does not alter their validation or behavior.

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|-------------|
| Per-call prompt construction (replacing module-load) adds latency to the interest pipeline's hot path | Low | Building a prompt string from an already-resolved, in-memory `AnalysisProfileConfigV1` is pure string formatting — no new I/O; the DB read for the active profile is the same per-call cost pattern already accepted for `ClientRules` (`summarizer.py:448-466`) |
| A client's catalog resolution is missed by one of the two consumers (`leads/router.py`, `calls/router.py`), leaving a stale hardcoded-constant read in production | Med | Task 4's RED test is a static-import guard (same pattern as P3's task 4.6) asserting no remaining direct `PRODUCT_CATALOG`/`NEED_TAGS` import exists in `leads/router.py`/`calls/router.py` once cutover completes |
| Frontend fallback to the static label map masks a real API failure indefinitely, hiding a broken profile endpoint | Low | The fallback path is logged (console warning) when triggered, matching P3's "env fallback is logged" precedent for visibility without blocking the user-facing render |
| Migration 0023's inline `insurance` template data drifts from `catalog.py`'s constants over time (someone edits one, not the other) | Low | The golden regression test (task 6) re-reads `catalog.py`'s `PRODUCT_CATALOG`/`NEED_TAGS` live and asserts the migrated revision's IDs match exactly — a drift breaks the test, not production, and is caught before merge |
| Empty-catalog skip accidentally also skips a dimension that should still run independent of the interest pipeline (e.g. `interest_level`, Agent 2) | Med | P5-D5 explicitly skips the interest pipeline (both agents) only when the PRODUCT catalog is empty; the need-tag skip is scoped to need-tag validation within Agent 1's existing run, not a second independent skip path — this distinction is unit-tested explicitly in task 3 |

## Rollback Plan

- **Templates + schema + migration (task 1)**: `alembic downgrade -1` drops `client_analysis_profile_revisions`, `clients.active_analysis_profile_revision_id`, and `call_analyses.analysis_profile_revision_id`; no runtime code depends on any of them yet — pure additive revert.
- **Profile service + API (task 2)**: revert the PR; nothing in the hot path calls the service yet.
- **Per-call catalog injection (task 3)**: revert the PR; `interests.py`/`pipeline.py`/`summarizer.py` revert to module-load `PRODUCT_CATALOG`/`NEED_TAGS` and no `analysis_profile_revision_id` stamping — explicitly the highest-risk revert, gated on task 3 never being combined with another task so this revert is isolated.
- **Consumer cutover (task 4)**: revert the PR; `leads/router.py`/`calls/router.py` revert to the direct module-level constant imports, untouched since task 3 already left `catalog.py` itself unmodified.
- **Frontend cutover (task 5)**: revert the PR; `dimension-labels.ts` reverts to the static-only map, zero backend impact either direction.
- **Full-suite verification (task 6)**: verification-only; a failure here blocks closing the change, it does not require reverting a specific task — triage against tasks 1-5 to find the regression.

## Dependencies

- Depends on `backend/alembic`'s current head, `20261003_0022_import_crm_yaml_integrations.py` (phase P3's last migration); this change's migration is chained starting at `20261003_0023`.
- Depends on `backend/app/tenants/revisions_service.py`'s generic private helpers (`_create_revision`/`_get_revision`/`_list_revisions`/`_activate_revision`/`_rollback_to_revision`) already factored out for 1a/1b's two-table reuse — this phase adds a third owner table (`client_analysis_profile_revisions`) to the same reuse pattern, no changes to the helpers themselves required.
- Independent of phase P3 (`client-integrations-secrets`) and phase 1b (`agent-config-inheritance`) — no shared tables, no shared resolver; all three phases may land in any relative order.
- No new third-party dependencies.

## Review / Deployment Strategy

Six task groups, each sized to review within a single PR (~≤400 changed lines target per tasks.md): (1) templates + schema + migration, (2) profile service + API, (3) per-call catalog injection + skip-when-empty + revision stamping (never combined with another task), (4) leads/calls consumer cutover, (5) frontend label cutover, (6) full suites + golden regression + rollout notes. See tasks.md for the full forecast and per-task RED/GREEN/rollback detail.

## Success Criteria

- [ ] `client_analysis_profile_revisions` and `clients.active_analysis_profile_revision_id` exist; migration 0023 seeds revision 1 for every existing client (Quintana = `insurance`, everyone else = `generic`)
- [ ] Quintana's resolved catalog and resulting Agent-1 prompt text are byte-identical before and after this change — the golden regression test
- [ ] `interests.py`'s Agent-1 prompt is built per call from the calling client's resolved catalog, not at module import time
- [ ] A client with an empty product catalog triggers zero Agent 1/2 calls for the interest dimension; `detected_interests` stays empty
- [ ] `call_analyses.analysis_profile_revision_id` is stamped on every newly analyzed call
- [ ] `leads/router.py` and `calls/router.py` resolve a client's catalog instead of importing `PRODUCT_CATALOG`/`NEED_TAGS` directly — verified by a static-import guard test
- [ ] `GET`/`PUT`/rollback/apply-template analysis-profile endpoints exist, validate unique ids and non-empty labels, and never rewrite an existing revision
- [ ] `dimension-labels.ts` reads labels from the profile API with the existing static map as an explicit, logged fallback
- [ ] Full backend and frontend test suites pass before closing the change

## Next Recommended Phase

**sdd-tasks** → the six-task breakdown in `tasks.md`. See `specs/analysis-profiles/spec.md` for the behavioral contract.
