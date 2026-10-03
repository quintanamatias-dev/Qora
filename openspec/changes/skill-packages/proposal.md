# Proposal: Qora Config Phase 4 — Skill Packages

## Intent

Today, a Qora voice agent's runtime "skills" — the on-demand knowledge the LLM can load mid-call via the `load_skill` tool — live entirely on disk, scattered under `backend/clients/{client}/agents/{agent}/skills/registry.yaml` plus one `*.agent-skill.md` file per entry. Only one client has real content: `quintana-seguros/agents/leads-agent/skills/registry.yaml` lists two skills (`auto-insurance-knowledge`, `lead-qualification`), each backed by its own markdown file; `quintana-seguros/agents/jaumpablo/skills/registry.yaml` is `skills: []`. The loader chain (`app/prompts/skill_loader.py:74` `load_skill_registry()` → `app/prompts/loader.py:138`/`:164` → `voice/context.py:242,259` index injection and allowlist build → the runtime tool `app/tools/skill_loader.py:57` `handle_load_skill()`, dispatched via `dispatcher.py:231-246`/`registry.py:27,63,81`, cached per session in `voice/session.py:45-49`, short-circuited in `webhook.py:400-420`) is filesystem-only: every skill edit is a file edit, lost on redeploy exactly like phase 3's `crm.yaml` problem, with no history, no rollback, and no way for a non-insurance client to reuse insurance-agnostic skill content without copy-pasting files between client directories.

The roadmap's phase 4 goal is explicit: "Skill packages (Qora package + client package with per-agent sections)." This change gives skills the same DB-backed, revisioned treatment phase 1a/1b gave agent/client config and phase 5 (`analysis-profiles`) gave the interest catalog: a `skill_packages` → `skills` → `skill_revisions` hierarchy, with a Qora-owned package of skills available to every agent, and a per-client package whose `general` section applies to every agent for that client and whose `agent` section applies to one named agent only. The runtime loader chain's public shape — `SkillRegistryEntry`, the `load_skill` tool contract, the allowlist/path-traversal security model — is preserved exactly; only the data source moves from the filesystem to the DB, mirroring phase 3's "keep the existing contract, change the backing store" precedent.

## Scope

### In Scope

- Three new tables: `skill_packages` (`id`, `owner_type` `qora`|`client`, `client_id` nullable FK, `name`, `created_at`/`updated_at`) — one Qora-owned package plus one package per client; `skills` (`id`, `package_id` FK, `slug`, `section` `general`|`agent`, `agent_id` nullable FK, `active_revision_id`) — one row per skill slot within a package, `agent_id` populated only when `section = "agent"`; `skill_revisions` (`id`, `skill_id` FK, `revision_number`, `content_md`, `filler_text`, `trigger_hint`, `description`, `source` `import`|`api`|`rollback`, `created_by`, `created_at`, `note`) — immutable, insert-only, reusing `revisions_service.py`'s generic private helpers (`_create_revision`/`_get_revision`/`_list_revisions`/`_activate_revision`/`_rollback_to_revision`) the same way `analysis-profiles` added a third owner table to that pattern. Rollback to an older revision creates a new revision copying the old content, never resurrects or rewrites history.
- Resolution for one agent's effective skill set: the Qora package's `general`-section skills, plus that agent's client package's `general`-section skills, plus that agent's client package's `agent`-section skills scoped to that agent. Slug collisions across these three sources resolve in order of specificity: agent-section > client-general-section > Qora-package, with the lower-priority entry dropped from the resolved set and the collision logged (documented behavior, not an error).
- Runtime cutover of the full loader chain — `app/prompts/skill_loader.py`'s `load_skill_registry()`, `app/prompts/loader.py`'s `load_agent_skills()`/`load_skill_registry_entries()`, `voice/context.py`'s index/allowlist injection, `app/tools/skill_loader.py`'s `handle_load_skill()`, `dispatcher.py`/`registry.py`'s routing — to read the resolved DB skill set instead of `registry.yaml` + `*.agent-skill.md` files. The `SkillRegistryEntry` dataclass shape, the `load_skill` tool's JSON contract, the per-session `voice/session.py` cache, and the `webhook.py` short-circuit behavior are unchanged; only the data source changes. `load_skill_force_injection`'s existing lock in `tenants/field_policy.py:42`/`tenants/config_standard.py:52` is unaffected — it governs whether `load_skill` is force-injected into the enabled tool list, not where skill content comes from.
- A registry/content cache keyed by `(agent_id, max revision id per contributing skill)`, loaded once per session (same cost profile as today's one-time-per-session file reads) and invalidated by any write through the API — never a DB round trip per conversational turn beyond what the loader chain already performs once per session today.
- One-time import migration: for every `backend/clients/*/agents/*/skills/registry.yaml` plus its referenced `*.agent-skill.md` files, create (or reuse) that client's package, insert one `skills` row per registry entry in the `agent` section for that agent, and seed revision 1 with the file's `content_md`/`filler_text`/`trigger_hint`/`description`. Inline YAML/markdown parsing, no `app.*` import (house pattern, same as phase 3's `crm.yaml` import and phase 5's catalog seed). Idempotent — re-running against an already-imported DB is a no-op, matching phase 3's `crm.yaml` import precedent. The filesystem files are deleted only in a later release after production has run the import, exactly as phase 3 deferred `crm.yaml` deletion.
- API: CRUD for packages and skills, `PUT` a skill's content (creates a new revision, never mutates an existing one), `GET` revision history, `POST` rollback (new revision copying an older one's content). Tenant-scoped — a client can manage only its own package; the Qora package is superadmin-only. No admin UI ships in this phase; the admin redesign is explicitly the user's own separate, later work, matching phase 5's precedent for the analysis-profile editor.

### Out of Scope

- An admin UI for browsing/editing packages, skills, or revisions — API-only, same precedent as `analysis-profiles`' deferred editor UI.
- Cross-client skill sharing beyond the fixed Qora-package/client-package/agent-section hierarchy (e.g. a client "subscribing" to another client's package) — not requested by the roadmap, no table shape supports it.
- Any change to the `load_skill` tool's security model (allowlist-before-filesystem-access, path-separator rejection) — that model moves to an allowlist-before-DB-lookup check with identical semantics; this change does not weaken or redesign it.
- Any change to `load_skill_force_injection`'s lock status or `tenants/field_policy.py`'s inheritance resolver — skills are a separate, independent config surface, exactly as `client-integrations-secrets` and `analysis-profiles` both declared CRM config and the interest catalog to be.
- Deleting the filesystem `registry.yaml`/`*.agent-skill.md` files in this phase — deferred to a later release, same rule as phase 3's `crm.yaml` deletion gate.
- Multi-language skill content, skill versioning beyond linear revisions (e.g. branching), or a skill marketplace — none of these are named in the roadmap for phase 4.

## Capabilities

> This section is the CONTRACT between proposal and specs phases.

### New Capabilities

- `skill-packages`: the `skill_packages`/`skills`/`skill_revisions` tables and their immutable revision lifecycle, the Qora-package/client-package(general+agent-section) resolution order and its collision rule, the one-time registry.yaml/*.agent-skill.md import migration, the runtime cutover of the full loader chain with an unchanged `SkillRegistryEntry`/`load_skill` contract, the per-session resolved-skill-set cache with write-invalidation, and the package/skill/revision CRUD + rollback API.

### Modified Capabilities

- None. `load_skill_force_injection` (locked in `tenants/field_policy.py`/`tenants/config_standard.py`) is unaffected — this phase changes where skill content is read from, not whether `load_skill` is force-injected into an agent's tool list. No existing spec requirement is superseded by this change.

## Approach

**Schema and import first, then resolution and cache, then the runtime cutover, then the API** — each layer additive until the runtime-cutover task, matching the staged-rollout precedent already used in phases 3 and 5.

1. Models (`SkillPackage`, `Skill`, `SkillRevision`) + schema migration `20261003_0025` — additive
2. One-time import migration `20261003_0026`: every `backend/clients/*/agents/*/skills/registry.yaml` + referenced `*.agent-skill.md` files → a client package's agent-section skills, revision 1 each — additive, idempotent
3. Skills service (CRUD, reused generic revisions helpers) + resolution function + per-session cache — additive, nothing in the runtime loader chain calls it yet
4. Runtime cutover: `skill_loader.py`/`loader.py`/`voice/context.py`/`tools/skill_loader.py`/`dispatcher.py` read the resolved DB skill set instead of the filesystem — the only behavioral cutover task, never combined with another task; golden regression: Quintana's `leads-agent` resolved registry and skill contents are byte-identical to the current files
5. API: packages/skills CRUD, `PUT` content → new revision, `GET` revisions, `POST` rollback
6. Full suites + rollout notes

## Affected Areas

| Area | Impact | Description |
|------|--------|--------------|
| `backend/app/tenants/models.py` | Modified | New `SkillPackage`, `Skill`, `SkillRevision` models |
| `backend/alembic/versions/20261003_0025_skill_packages_schema.py` (new) | New | `CREATE TABLE skill_packages`, `CREATE TABLE skills`, `CREATE TABLE skill_revisions`, with `unique(package_id, slug, agent_id)` on `skills` |
| `backend/alembic/versions/20261003_0026_import_skill_registries.py` (new) | New | One-time import of every `backend/clients/*/agents/*/skills/registry.yaml` + referenced `*.agent-skill.md` into a client package's agent section, revision 1 each; idempotent; no `app.*` import |
| `backend/app/skills/service.py` (new) | New | Package/skill/revision CRUD built on `revisions_service.py`'s generic helpers; `resolve_agent_skills(client_id, agent_slug) -> list[SkillRegistryEntry]` implementing the Qora/client-general/agent-section resolution + collision rule |
| `backend/app/skills/cache.py` (new) | New | Per-session resolved-skill-set cache keyed by `(agent_id, max contributing revision ids)`, invalidated on any write |
| `backend/app/skills/router.py` (new) | New | CRUD for packages/skills; `PUT` skill content → new revision; `GET` revisions; `POST` rollback; tenant-scoped, Qora package superadmin-only |
| `backend/app/prompts/skill_loader.py` | Modified | `load_skill_registry()` resolves from the DB via `resolve_agent_skills()` instead of parsing `registry.yaml`; `SkillRegistryEntry` shape unchanged |
| `backend/app/prompts/loader.py` | Modified | `load_agent_skills()`/`load_skill_registry_entries()` (lines 138, 164 today) call the DB-backed resolver instead of the filesystem parser |
| `backend/app/voice/context.py` | Modified | Lines 242, 259 — index/allowlist injection reads the resolved DB skill set |
| `backend/app/tools/skill_loader.py` | Modified | `handle_load_skill()` validates against the resolved DB allowlist and reads `content_md` from the active revision instead of a markdown file; path-separator/allowlist security checks unchanged in spirit, re-targeted at DB lookups |
| `backend/app/tools/dispatcher.py` | Modified | Lines 231-246 — `load_skill` routing unchanged in shape, sources content via the new handler |
| `backend/app/tools/registry.py` | Modified | Lines 27, 63, 81 — unchanged tool definition/filler-phrase wiring, no behavioral change expected |
| `backend/app/voice/session.py` | Modified | Lines 45-49 — per-session `loaded_skills` cache unchanged in shape; sources content from the DB-backed handler |
| `backend/app/voice/webhook.py` | Modified | Lines 400-420 — short-circuit logic unchanged; still matches on `event.function_name == "load_skill"` and the session cache |
| `backend/clients/*/agents/*/skills/registry.yaml` + `*.agent-skill.md` | Unaffected (read-only legacy, deletion deferred) | No longer read by any runtime path after task 4; files remain on disk until a later release deletes them |

## Safety Model

1. **Quintana's runtime behavior is byte-identical, provably** — the golden regression test (task 4) asserts the resolved registry entries and skill contents for `leads-agent` exactly match today's `registry.yaml` + `*.agent-skill.md` files, field for field, string for string.
2. **Revisions are immutable, rollback is additive** — exactly like 1a/1b/P3/P5's revision tables, no `UPDATE`/`DELETE` path exists on `skill_revisions`; a rollback creates a new revision copying an older one's content, never rewrites history.
3. **The `load_skill` allowlist-before-access security model is preserved, not weakened** — `handle_load_skill()` still rejects any skill name not present in the resolved, session-scoped entry list before any content lookup; the path-separator/`..`-rejection check carries over conceptually (now guarding a DB slug lookup, not a filesystem path) so no untrusted input reaches a query unchecked.
4. **One client's skill-package edit never affects another client** — resolution and the per-session cache are keyed by `(client_id, agent_slug)`/`agent_id`; a write to one client's package invalidates only that client's cache entries, matching phase 3's per-client cache-invalidation precedent (`IntegrationStore.invalidate(client_id)`).
5. **Import is idempotent and reversible** — re-running the import migration against an already-imported DB creates no duplicate rows (matched by `(package_id, slug, agent_id)`); the filesystem files remain the rollback target until a later release deletes them, same as phase 3's `crm.yaml` deferred-deletion rule.

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|-------------|
| The runtime cutover (task 4) silently changes resolved skill content for `leads-agent` (e.g. a markdown-escaping or whitespace difference between file read and DB column read) | Med | The golden regression test asserts byte-identical content strings, not just structural equality; task 4 is never combined with another task so a regression is isolated to one PR |
| Slug collisions across the three resolution sources produce a surprising silently-dropped skill | Low | The collision rule (agent-section > client-general > Qora) is explicit, documented in the spec, and the dropped lower-priority entry is logged at `WARNING` so an operator can see it, not just infer it from behavior |
| The per-session cache (`skills/cache.py`) serves a stale skill set after a write made through a path other than the API | Low | Same documented posture as phase 3's `IntegrationStore`: cache coherence is API-write-driven; an out-of-band DB write is an operational anti-pattern, not a supported path |
| The import migration (task 2) double-imports if run twice against a partially-migrated DB | Low | Idempotency is enforced by matching on `(package_id, slug, agent_id)` before insert — a re-run is a no-op for already-imported rows, same pattern phase 3's `crm.yaml` import used |
| A future runtime consumer reads `registry.yaml` directly, missed by this phase's grep | Med | Task 4 includes a static-import regression guard (same pattern as phase 3's task 4.6 and phase 5's task 4.3) asserting no remaining direct `registry.yaml`/`*.agent-skill.md` filesystem read exists in `backend/app/` |

## Rollback Plan

- **Models + schema migration (task 1)**: `alembic downgrade -1` drops `skill_packages`, `skills`, `skill_revisions`; no runtime code depends on them yet — pure additive revert.
- **Import migration (task 2)**: `alembic downgrade -1`; imported rows are removed, filesystem files are untouched and remain the source of truth since task 4 has not yet cut over any reader.
- **Service + resolution + cache (task 3)**: revert the PR; nothing in the runtime loader chain calls it yet.
- **Runtime cutover (task 4)**: revert the PR; every reader in the loader chain reverts to parsing `registry.yaml`/`*.agent-skill.md`, both still present on disk — explicitly the highest-risk revert, isolated because this task is never combined with another.
- **API (task 5)**: revert the PR; package/skill/revision endpoints are removed, no runtime impact since the loader chain (task 4) does not depend on the API existing.
- **Full-suite verification (task 6)**: verification-only; a failure blocks closing the change, triage against tasks 1-5 to find the regression.

## Dependencies

- Depends on `backend/alembic`'s current head after phase 5, `20261003_0024_analysis_profiles_schema.py`; this change's migrations are chained starting at `20261003_0025`.
- Depends on `backend/app/tenants/revisions_service.py`'s generic private helpers, already reused by a third owner table in `analysis-profiles` — this phase adds a fourth owner table (`skill_revisions`) to the same reuse pattern, no changes to the helpers themselves required.
- Independent of `client-integrations-secrets` (phase 3) and `analysis-profiles` (phase 5) — no shared tables, no shared resolver; all phases may land in any relative order.
- Independent of `agent-config-inheritance` (phase 1b) — `load_skill_force_injection`'s lock in `tenants/field_policy.py`/`config_standard.py` is read-only context for this change, not modified by it.
- No new third-party dependencies.

## Review / Deployment Strategy

Five task groups, each sized to review within a single PR (~≤400 changed lines target per tasks.md): (1) models + schema migration, (2) one-time import migration, (3) skills service + resolution + cache, (4) runtime cutover of the full loader chain (never combined with another task), (5) API; a sixth group runs the full suites and records rollout notes. See tasks.md for the full forecast and per-task RED/GREEN/rollback detail.

## Success Criteria

- [ ] `skill_packages`, `skills`, `skill_revisions` exist; the one-time import migration creates a client-package agent-section skill + revision 1 for every existing `backend/clients/*/agents/*/skills/registry.yaml` entry
- [ ] Quintana's `leads-agent` resolved registry entries and skill contents are byte-identical to today's `registry.yaml` + `*.agent-skill.md` files — the golden regression test
- [ ] Resolution for any agent combines the Qora package's general-section skills, that agent's client package's general-section skills, and that agent's client package's agent-section skills, with the documented agent > client-general > Qora collision rule
- [ ] `SkillRegistryEntry`'s shape and the `load_skill` tool's JSON contract are unchanged; every loader-chain consumer enumerated in Affected Areas reads via the DB resolver, not `registry.yaml`/`*.agent-skill.md`, by the end of task 4
- [ ] No DB round trip occurs per conversational turn beyond what the loader chain already performs once per session today
- [ ] The import migration is idempotent — re-running it against an already-imported DB creates no duplicate rows
- [ ] CRUD, `PUT` content (new revision), `GET` revisions, and `POST` rollback all work tenant-scoped, with the Qora package restricted to superadmin
- [ ] Full backend test suite passes before closing the change

## Next Recommended Phase

**sdd-tasks** → the five-task breakdown in `tasks.md`. See `specs/skill-packages/spec.md` for the behavioral contract.
