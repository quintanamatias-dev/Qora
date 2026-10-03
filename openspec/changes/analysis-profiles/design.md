# Design: Qora Config Phase 5 — Analysis Profiles

## Technical Approach

Decouple the universal post-call interest-detection pipeline's product/need-tag catalog from Quintana Seguros's hardcoded `catalog.py` constants by giving every client a versioned, revisioned analysis profile — mirroring the insert-only revision pattern already proven by 1a (`agent_config_revisions`), 1b (`client_config_revisions`), and P3's secrets tables. The rule engine (next-action thresholds) stays exactly where it is, on `Client` columns; only the catalog the interest-detection dimension validates against becomes per-client and per-call. Two code-only vertical templates (`insurance`, `generic`) seed every client's first revision via a migration that is self-contained (no `app.*` import, matching house pattern), and `interests.py`'s prompt construction moves off module load to a per-call build so a client's catalog can actually vary at runtime — something the current architecture structurally cannot do.

## Architecture Decisions

| Decision | Choice | Alternatives Rejected | Rationale |
|----------|--------|------------------------|-----------|
| **P5-D1 — Next-action thresholds stay on `Client` columns; the profile owns only catalog + labels** | `next_action_max_attempts`, `next_action_min_interest_for_followup`, `next_action_close_on_hard_rejection`, the `scheduler_*` columns, and `analysis_language` remain exactly where they are today — flat columns on `Client`, already API-editable, already consumed by `summarizer.py:448-466`'s `ClientRules` construction. The analysis profile introduced by this phase owns exactly two things: the product catalog (`id`, `label_es`, `label_en`, `description`) and the need-tag catalog (`id`, `label_es`, `label_en`). The rule engine itself — the logic in `next_action.py` that consumes `ClientRules` to decide next actions — stays in code, unchanged. | (a) Fold the next-action thresholds into the same revisioned profile, since both are "client-specific analysis config." (b) Move the rule engine's logic itself into the profile's JSON config (data-driven rules). | (a) is rejected because the thresholds are already a solved, working, API-editable surface with zero reported problems — survey critical #5 is specifically about the hardcoded PRODUCT catalog, not about threshold editability. Moving a working surface into a new revisioned table for consistency's sake, with no reported pain point, is scope creep that also complicates the migration (thresholds would need their own seed-from-existing-columns step, doubling migration risk for no behavioral gain). (b) is rejected outright: the rule engine's branching logic (attempts, interest-level comparisons, rejection handling) is exactly the kind of behavior that benefits from code review and type-checking; turning it into interpreted JSON config buys flexibility nobody has asked for at the cost of making a core business rule invisible to `git diff` and untestable by normal unit tests. |
| **P5-D2 — `client_analysis_profile_revisions` (immutable) + `clients.active_analysis_profile_revision_id`, reusing the generic revisions service** | New table `client_analysis_profile_revisions(id, client_id FK, revision_number, config JSON, source, created_by, created_at, note)` — insert-only, no `UPDATE`/`DELETE` path, exactly 1a/1b's pattern. `config` is `{schema_version, vertical, products: [{id, label_es, label_en, description}], need_tags: [{id, label_es, label_en}]}`. `clients.active_analysis_profile_revision_id` is a nullable FK pointing at the active revision. The service layer reuses `revisions_service.py`'s existing generic private helpers (`_create_revision`, `_get_revision`, `_list_revisions`, `_activate_revision`, `_rollback_to_revision`), parameterized by `(model=ClientAnalysisProfileRevision, owner_id_attr="client_id", active_pointer_attr="active_analysis_profile_revision_id")` — the same reuse already demonstrated for `Agent`/`AgentConfigRevision` and `Client`/`ClientConfigRevision` in that module. Rollback creates a new revision copying an old one's `config`, never rewrites history. | (a) A single mutable `analysis_profiles` table (no revision history), matching P3's `client_integrations`'s "mutable, audited by columns" pattern instead of 1a/1b's immutable-revision pattern. (b) A brand-new, bespoke revisions implementation instead of reusing `revisions_service.py`'s generic helpers. | (a) is rejected because a product catalog edit directly determines how historical `CallAnalysis.products` data should be interpreted (P5-D6) — unlike P3's CRM config, where "what was the Airtable base ID three edits ago" has no analogous downstream data-interpretation dependency, here the exact catalog in effect when a call was analyzed is load-bearing for reading that call's stored products correctly. Revision history is not optional nicety here, it is a requirement for historical data integrity. (b) is rejected as pure duplication: `revisions_service.py`'s generic helpers already exist, are tested, and are explicitly designed (per that module's own docstring, D11 from 1b) for exactly this kind of reuse across owner tables — writing a third, parallel revision implementation for the same insert-only/rollback-creates-new-revision contract would be the premature-abstraction mistake in reverse (duplicating a working abstraction instead of reusing it). |
| **P5-D3 — Vertical templates live in code; `insurance` is byte-identical to today's catalog.py, `generic` is empty** | `backend/app/analysis/profiles/templates.py` defines two `ProfileTemplate` Python constants: `insurance` (the exact 9 product IDs from `catalog.py:27-37` and exact 10 need-tag IDs from `catalog.py:41-59`, with `label_es`/`label_en` populated from `frontend/src/config/dimension-labels.ts`'s existing entries for those same IDs) and `generic` (`products=[]`, `need_tags=[]`). New clients default to `generic`. Creating a profile from a template, or resetting an existing profile back to one, is an explicit API action (`POST .../analysis-profile/apply-template {vertical}`) that creates a new revision — never an implicit side effect of client creation beyond the one-time migration seed. | (a) Store templates as DB rows (a `profile_templates` table), editable via a separate admin API. (b) Infer "insurance" vs "generic" from some existing client attribute automatically rather than an explicit action. | (a) is rejected because templates are a small, fixed, code-reviewed set (exactly two today) with no demonstrated need for runtime editability — turning them into DB rows adds a whole CRUD surface (with its own migration, its own API, its own validation) for content that changes at the pace of a PR review, not a panel click; this mirrors 1b's own rejection of a DB-backed Qora standard (P5 follows the same "fixed set, lives in code" precedent 1b's `AgentConfigStandard` already established). (b) is rejected because silent inference is exactly the kind of implicit behavior that caused survey critical #5 in the first place — a NEW client silently getting treated as "insurance" based on some heuristic is the same hardcoding problem relocated, not solved; `generic` as the explicit default plus an explicit apply-template action keeps the choice visible and auditable (who applied `insurance`, when, as a revision with a `source`/`created_by`). |
| **P5-D4 — Migration 0023 seeds every client; Quintana gets byte-identical `insurance` data inline, everyone else gets `generic`** | `backend/alembic/versions/20261003_0023_analysis_profiles_schema.py` creates both new tables, adds `clients.active_analysis_profile_revision_id` and `call_analyses.analysis_profile_revision_id`, then inserts revision 1 for every existing `clients` row: Quintana Seguros's row gets the `insurance` template's data **inlined directly in the migration file** (literal product/need-tag IDs and labels, not an import of `templates.py` — migrations never import `app.*`, the same house pattern P3's import migration already follows), every other client gets `generic`'s empty data. A golden regression test (task 6) asserts Quintana's post-migration resolved catalog exactly matches `catalog.py`'s live `PRODUCT_CATALOG`/`NEED_TAGS` constants — behavior for Quintana is provably unchanged. | (a) Only create the tables in the migration; seed revisions lazily on first API read (a client with no revision gets `generic` computed on the fly, nothing persisted until an explicit write). (b) Have the migration import `backend/app/analysis/profiles/templates.py` directly to avoid duplicating the `insurance` IDs inline. | (a) is rejected because "no revision exists yet" and "revision 1 is the generic empty catalog" are observably different states for the Success Criteria's "every existing client has revision 1" requirement, and because `summarizer.py` needs to stamp a concrete `analysis_profile_revision_id` on every `CallAnalysis` row from day one — a lazily-materialized revision means the first several calls for most clients would have a `None` revision id, reintroducing exactly the "historical data isn't interpretable" gap P5-D6 exists to close. (b) is rejected for the same reason P3's D6 rejected importing `app.*` from a migration: Alembic migrations in this house run standalone and must not depend on application module import order or availability at migrate-time; the small duplication cost (9 product IDs + 10 need-tag IDs, inlined once) is explicitly accepted and caught by the golden regression test if it ever drifts from `catalog.py`. |
| **P5-D5 — Empty product catalog skips the interest pipeline entirely; empty need tags skip need-tag validation within Agent 1** | When `resolve_client_catalog(client_id).products` is empty, `pipeline.py`'s `run_interest_pipeline` returns immediately with `InterestsAxis(items=[])` and an empty `interest_level` result — **neither Agent 1 nor Agent 2 is called**. This is distinct from today's existing error-marker contract (`pipeline.py`'s docstring: error dicts vs. normal empty results) — a skip is a normal, non-error empty result, not a failure marker. When the catalog's need tags are empty but products are non-empty, Agent 1 still runs for product detection but its need-tag list in the prompt is empty and any extracted `needs` are discarded/empty — this is a narrower skip scoped inside Agent 1's existing run, not a second pipeline-level skip. | (a) Still call Agent 1/2 with an empty product list in the prompt, relying on the LLM to naturally return zero items. (b) Skip need tags the same way as products — a pipeline-level skip whenever EITHER list is empty. | (a) is rejected as wasted cost for a guaranteed-useless call: an LLM given "VALID PRODUCTS: (none)" has no possible correct non-empty output, so the call is pure latency and token cost with a deterministic result — skipping it is a pure efficiency win with no behavioral difference. (b) is rejected because products and need tags are not symmetric in the existing schema: `InterestItem.needs` is a sub-field of a detected product interest (`interests.py`'s `InterestItem` model) — if products are non-empty, Agent 1 still has useful work to do (detecting WHICH product, with evidence) even if it has nothing to tag needs with; conflating the two into one skip condition would silently suppress legitimate product-interest detection for a client that configured products but genuinely has no need-tag taxonomy yet. |
| **P5-D6 — `call_analyses.analysis_profile_revision_id` (nullable) for historical interpretability** | `CallAnalysis` gets a new nullable column `analysis_profile_revision_id`, stamped by `summarizer.py` at analysis time with the client's currently-active profile revision id. Nullable because rows written before this migration have no value — they are interpreted under the implicit assumption of `catalog.py`'s original constants, documented as a migration-boundary note, not backfilled. | (a) Backfill historical rows with a synthetic "pre-migration" revision id pointing at a reconstructed `insurance` revision. (b) Store the full resolved catalog JSON directly on `CallAnalysis` instead of a revision id (denormalized copy). | (a) is rejected as unnecessary complexity for a boundary that is already unambiguous: every `CallAnalysis` row written before this migration was necessarily produced under `catalog.py`'s then-current constants (the only catalog that existed), so a `NULL` revision id combined with the row's `created_at` predating the migration is itself sufficient documentation — synthesizing a fake historical revision row to backfill into is solving a problem that doesn't exist. (b) is rejected because it reintroduces exactly the kind of denormalized, drift-prone duplication the revision-id-as-pointer pattern exists to avoid (the same reasoning 1a's `agent_config_revision_id` on `call_sessions` already established) — a foreign key to the immutable revision is strictly smaller and cannot drift from the revision it points to, whereas a JSON copy on every `CallAnalysis` row could silently diverge from its own revision if any code path ever touched it after the fact. |
| **P5-D7 — API surface: CRUD + revisions + rollback + apply-template; frontend labels with a static fallback, no editor UI** | `GET`/`PUT /clients/{client_id}/analysis-profile` (PUT validates: product ids unique within the submitted list, need-tag ids unique within the submitted list, every `label_es`/`label_en` non-empty — rejecting with 422 and the exact offending field list on violation), `GET .../analysis-profile/revisions`, `POST .../analysis-profile/rollback` (body: target revision id; creates a new revision copying the target's config), `POST .../analysis-profile/apply-template` (body: `{vertical: "insurance" \| "generic"}`; creates a new revision from that template's current code-defined data). Frontend: `dimension-labels.ts`'s existing lookup function is modified to first check labels fetched from `GET .../analysis-profile`, falling back to the existing static map when the fetch fails or a specific id is missing from the fetched profile — logged as a console warning when the fallback path is used (matching P3's "env fallback is logged" visibility precedent). No profile-editor UI ships in this phase; `analysis-panel.tsx`'s chip rendering is unaffected — it already reads through `dimension-labels.ts`'s lookup function, so the label source changes underneath it transparently. | (a) Design a from-scratch admin API shape, unconstrained by any existing precedent. (b) Ship a minimal inline profile editor in the admin panel as part of this phase, since the API already exists. | (a) is rejected in favor of matching 1a/1b/P3's already-established revision-API shape (`GET`/`PUT` current, `GET` revisions, `POST` rollback) — consistency with three prior phases' API conventions lowers the learning cost for whoever builds the eventual editor UI, and "keep the existing shape where there's precedent" is the same argument P3's own P3-D7 made for `crm_config_router.py`. (b) is explicitly rejected per the task brief: the admin editor UI is owned by the user as separate, later work — shipping a half-built editor now would either be throwaway work (if the user's eventual design differs) or scope creep that blocks this phase's actual goal (closing survey critical #5's hardcoding problem) behind UI design decisions that are out of this change's authority to make. |

## Data Flow

```
READ PATH — interest pipeline (per call)
───────────────────────────────────────────────────────────────────────────
summarizer.py (post-call analysis orchestration)
       │
       ▼
resolve_client_catalog(client_id)              (backend/app/analysis/profiles/service.py)
       │
       ▼
load Client.active_analysis_profile_revision_id → load client_analysis_profile_revisions row
       │
       ▼
parse config JSON → AnalysisProfileConfigV1 (products, need_tags)
       │
       ▼
   products empty? ──yes──► run_interest_pipeline returns InterestsAxis(items=[]) immediately
       │ no                  (NO Agent 1/2 call — P5-D5)
       ▼
pipeline.run_interest_pipeline(catalog, transcript, ...)
       │
       ▼
interests.py: _build_prompt(catalog, language)   (built PER CALL, not at module load)
       │
       ▼
Agent 1 (interests) runs against this call's catalog
       │
       ▼
Agent 2 (interest_level) runs with Agent 1's output
       │
       ▼
summarizer.py stamps ca.analysis_profile_revision_id = the resolved revision's id (P5-D6)
       │
       ▼
ca.products / ca.detected_interests / ca.specific_needs written as today


READ PATH — consumers (leads/calls routers)
───────────────────────────────────────────────────────────────────────────
leads/router.py (interest rollup)          calls/router.py (CallAnalysisResponse)
       │                                           │
       ▼                                           ▼
resolve_client_catalog(client_id)          resolve_client_catalog(client_id)
       │                                           │
       ▼                                           ▼
filter by resolved product_set/need_set     label resolution (if any) uses resolved catalog
   (replaces module-level PRODUCT_CATALOG/NEED_TAGS import)


WRITE PATH — profile edit
──────────────────────────────────────────────
PUT /clients/{client_id}/analysis-profile   { products: [...], need_tags: [...] }
       │
       ▼
validate: unique product ids, unique need-tag ids, every label non-empty  ──fail──► 422 + field list
       │ pass
       ▼
_create_revision(ClientAnalysisProfileRevision, client_id, config, source="api", created_by, note)
       │
       ▼
UPDATE clients.active_analysis_profile_revision_id = new revision id
       │
       ▼
response: the new revision's config + revision_number


WRITE PATH — rollback
──────────────────────────
POST /clients/{client_id}/analysis-profile/rollback   { target_revision_id }
       │
       ▼
_get_revision(target_revision_id, scoped to client_id) ──not found/wrong client──► 404
       │ found
       ▼
_rollback_to_revision(...) → _create_revision(config=target.config, source="rollback")
       │
       ▼
UPDATE clients.active_analysis_profile_revision_id = the NEW revision's id (never the target's id)


WRITE PATH — apply-template
───────────────────────────────
POST /clients/{client_id}/analysis-profile/apply-template   { vertical: "insurance" | "generic" }
       │
       ▼
load templates.py's named template (code constant)
       │
       ▼
_create_revision(config=template.config, source="api", note=f"applied template: {vertical}")
       │
       ▼
UPDATE clients.active_analysis_profile_revision_id = new revision id
```

## File Changes

| File | Action | Description |
|------|--------|--------------|
| `backend/app/analysis/profiles/templates.py` | Create | `insurance` and `generic` `ProfileTemplate` constants (code data, P5-D3) |
| `backend/app/analysis/profiles/schema.py` | Create | `AnalysisProfileConfigV1`, `ProductEntry`, `NeedTagEntry` Pydantic models |
| `backend/app/analysis/profiles/service.py` | Create | `resolve_client_catalog`, `create_revision`/`get_revision`/`list_revisions`/`rollback`/`apply_template` built on `revisions_service.py`'s generic helpers |
| `backend/app/analysis/profiles/router.py` | Create | `GET`/`PUT .../analysis-profile`, `GET .../analysis-profile/revisions`, `POST .../analysis-profile/rollback`, `POST .../analysis-profile/apply-template` |
| `backend/app/tenants/models.py` | Modify | `ClientAnalysisProfileRevision` model (`client_analysis_profile_revisions` table); `Client.active_analysis_profile_revision_id` FK |
| `backend/app/calls/models.py` | Modify | `CallAnalysis.analysis_profile_revision_id` (nullable FK) |
| `backend/alembic/versions/20261003_0023_analysis_profiles_schema.py` | Create | `CREATE TABLE client_analysis_profile_revisions`; two new FK columns; seeds revision 1 for every existing client (Quintana = inline `insurance` data, everyone else = inline `generic` data) |
| `backend/app/analysis/universal/interest/interests.py` | Modify | `_build_prompt` takes the resolved catalog as a parameter; `DIMENSION["prompt"]` module-level construction removed; the analyzer entry point builds the prompt per call |
| `backend/app/analysis/universal/interest/pipeline.py` | Modify | `run_interest_pipeline` accepts the resolved catalog; short-circuits to an empty result when products are empty (P5-D5) |
| `backend/app/summarizer.py` | Modify | Calls `resolve_client_catalog`, passes it into the pipeline, stamps `ca.analysis_profile_revision_id` |
| `backend/app/leads/router.py` | Modify | Lines 544-628 — reads the resolved catalog instead of importing `PRODUCT_CATALOG`/`NEED_TAGS` directly |
| `backend/app/calls/router.py` | Modify | Line ~695 area — reads the resolved catalog for any label resolution |
| `frontend/src/config/dimension-labels.ts` | Modify | Lookup function checks a fetched profile first, falls back to the existing static map (logged on fallback) |
| `backend/app/analysis/universal/interest/catalog.py` | Unmodified | `PRODUCT_CATALOG`/`NEED_TAGS` remain as the literal source the migration's inline data and the `insurance` template are checked against (golden regression) |

## Interfaces / Contracts

```python
# backend/app/analysis/profiles/schema.py
class ProductEntry(BaseModel):
    id: str
    label_es: str
    label_en: str
    description: str | None = None

class NeedTagEntry(BaseModel):
    id: str
    label_es: str
    label_en: str

class AnalysisProfileConfigV1(BaseModel):
    schema_version: Literal[1] = 1
    vertical: str                      # "insurance" | "generic" | future verticals
    products: list[ProductEntry] = []
    need_tags: list[NeedTagEntry] = []
```

```python
# backend/app/analysis/profiles/templates.py
class ProfileTemplate(BaseModel):
    vertical: str
    config: AnalysisProfileConfigV1

insurance: ProfileTemplate  # byte-identical to catalog.py's 9 products / 10 need tags
generic: ProfileTemplate    # products=[], need_tags=[]
```

```python
# backend/app/analysis/profiles/service.py
async def resolve_client_catalog(
    session: AsyncSession, client_id: str
) -> AnalysisProfileConfigV1:
    """Loads the client's active revision; returns its config. Every client
    has revision 1 seeded by migration 0023, so this never returns None for
    an existing client — a missing Client row is the caller's own error,
    not a case this function handles."""
```

```python
# backend/app/analysis/universal/interest/pipeline.py (modified signature)
async def run_interest_pipeline(
    client: AsyncOpenAI,
    transcript: str,
    catalog: AnalysisProfileConfigV1,
    language: str,
) -> tuple[dict, dict]:
    """Returns (interests_result, level_result). When catalog.products is
    empty, returns (InterestsAxis(items=[]).model_dump(), {}) immediately —
    a normal empty result, NOT the existing error-marker shape (P5-D5)."""
```

```python
# backend/app/tenants/models.py — new model
class ClientAnalysisProfileRevision(Base):
    __tablename__ = "client_analysis_profile_revisions"
    __table_args__ = (UniqueConstraint("client_id", "revision_number"),)
    id: Mapped[str]
    client_id: Mapped[str]            # FK clients.id
    revision_number: Mapped[int]
    config: Mapped[str]               # JSON — AnalysisProfileConfigV1
    source: Mapped[str]               # "import" | "api" | "rollback"
    created_by: Mapped[str]
    created_at: Mapped[datetime]
    note: Mapped[str | None]
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|---------------|----------|
| Unit | `AnalysisProfileConfigV1`/`ProductEntry`/`NeedTagEntry` validation | Duplicate product id within one profile → `ValidationError`; empty `label_es`/`label_en` → `ValidationError` |
| Unit | `templates.insurance` matches `catalog.py` exactly | Assert the template's product ids == `set(PRODUCT_CATALOG)` and need-tag ids == `set(NEED_TAGS)`, byte-for-byte — the drift-detection test for P5-D4's risk |
| Unit | `resolve_client_catalog` | Seeded client with an active revision → returns matching config; a client row pointing at a revision_id that doesn't belong to it (cross-tenant) → never resolves that revision (same tenant-scoping precedent as `revisions_service.py`'s existing lookups) |
| Unit | `run_interest_pipeline` empty-catalog skip | Empty `products` → both agents are NOT called (assert via a call-count mock on the OpenAI client); non-empty `products` + empty `need_tags` → Agent 1 IS called, needs come back empty, no pipeline-level skip (P5-D5's two distinct paths) |
| Unit | `_build_prompt` is call-scoped, not module-scoped | Two different catalogs passed to `_build_prompt` in the same process produce two different prompt strings — the literal regression test proving module-load injection is gone |
| Unit | Profile write validation | `PUT .../analysis-profile` with a duplicate product id, or an empty label → 422 with the exact offending field named |
| Integration | Revision immutability + rollback | `PUT` twice creates two revisions, not one row mutated in place; `POST rollback` to revision 1 creates revision 3 (not resurrecting revision 1), and `active_analysis_profile_revision_id` points at revision 3 afterward |
| Integration | Apply-template creates a new revision from code data | `POST apply-template {vertical: "insurance"}` on a `generic` client creates a revision whose config matches `templates.insurance.config` exactly |
| Integration | `analysis_profile_revision_id` stamped correctly | Run a full post-call analysis against a seeded client; assert the resulting `CallAnalysis.analysis_profile_revision_id` equals that client's active revision id at analysis time |
| Integration | Historical interpretability survives a later profile edit | Analyze a call, then edit the client's profile (new revision); assert the EARLIER `CallAnalysis` row's `analysis_profile_revision_id` still points at the OLD revision, not the new one |
| Regression (golden) | Quintana byte-identical before/after | Seed Quintana via migration 0023, call `resolve_client_catalog`, assert the resulting product/need-tag id sets exactly equal `catalog.py`'s live constants; build Agent 1's prompt from the resolved catalog and assert it matches the prompt `interests.py` would have built pre-change for the same transcript/language inputs |
| Regression | Consumer cutover guard | A static-import test (task 4) asserts no remaining direct `from app.analysis.universal.interest.catalog import PRODUCT_CATALOG` / `NEED_TAGS` import exists in `leads/router.py` or `calls/router.py` |
| Regression | Existing interest-pipeline test suite still passes | `backend/tests/.../test_interests.py`, `test_pipeline.py` (confirmed existing suites) continue to pass against the per-call catalog parameter, adjusted only where a test directly asserted the module-level prompt constant (those specific assertions are updated to build the prompt via the new per-call function with the `insurance` catalog, not removed) |
| Frontend | Label fallback behavior | A mocked failed `GET .../analysis-profile` → `dimension-labels.ts`'s lookup falls back to the static map and logs a console warning; a successful fetch with a label for a given id → the fetched label is used, not the static one |

## Migration / Rollout

**Staged rollout** (see tasks.md for full per-task RED/GREEN/rollback breakdown):

1. Templates + schema + migration 0023 — additive; every client gets revision 1 seeded, nothing reads it yet
2. Profile service + API — additive, nothing in the hot path calls it yet
3. Per-call catalog injection in `interests.py`/`pipeline.py` + skip-when-empty + `summarizer.py` stamping — the only reader-facing behavioral change; gated on the golden regression test passing for Quintana before this task is considered done
4. `leads/router.py`/`calls/router.py` consumer cutover — gated on task 3's stamping being in place so the resolved catalog these consumers read is sourced consistently
5. `dimension-labels.ts` frontend cutover — independent of backend task ordering beyond the API existing (task 2)
6. Full backend + frontend suites, golden regression re-run, rollout notes

**Existing-client safe path**: Quintana Seguros is the only client with real production interest-detection usage today (confirmed via the survey). Migration 0023 seeds its revision 1 with byte-identical `insurance` data; task 3's golden regression test is the explicit, independently re-runnable proof that no behavior changed for Quintana before task 3 is considered mergeable — not an assumption, a gate.

## Rollback Plan

| Stage | Action | Notes |
|-------|--------|-------|
| After task 1 (templates + schema + migration) | `alembic downgrade -1`; remove `templates.py`/`schema.py` | Pure addition, no runtime code depends on either table yet |
| After task 2 (profile service + API) | Revert PR | Pure addition, nothing in the hot path calls it yet |
| After task 3 (per-call catalog injection) | Revert PR | `interests.py`/`pipeline.py`/`summarizer.py` revert to module-load `PRODUCT_CATALOG`/`NEED_TAGS` and no revision-id stamping — explicitly the highest-risk revert, never combined with another task so this revert is isolated and clean |
| After task 4 (consumer cutover) | Revert PR | `leads/router.py`/`calls/router.py` revert to the direct module-level constant imports; `catalog.py` itself was never modified, so this revert has no further dependency |
| After task 5 (frontend cutover) | Revert PR | `dimension-labels.ts` reverts to the static-only map; zero backend impact either direction |
| After task 6 (full suites + rollout) | n/a — verification only | A failure here blocks closing the change until fixed or explicitly triaged as pre-existing/unrelated; does not require reverting a specific task |

## Open Questions

- [ ] Should a profile's `vertical` field be validated against a fixed enum of known verticals, or remain a free-form string for future verticals added without a code change? Free-form is sufficient for this phase's two templates (`insurance`, `generic`); revisit if a third vertical's naming convention becomes a real need.
- [ ] Should the apply-template action be blocked when a client already has non-empty, hand-edited products (to avoid silently discarding manual edits)? Not blocking tasks 1-6; the current design treats apply-template as an explicit, informed action (the operator sees the current profile via `GET` before choosing to apply a template) — revisit if an accidental overwrite is reported in practice.
- [ ] Whether `description` on `ProductEntry` should be required rather than optional, for a future admin editor UI's benefit — optional is sufficient for this phase since no editor UI ships; the user's later editor-UI work may tighten this.
