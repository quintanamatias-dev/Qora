# Design: Qora Config Phase 4 — Skill Packages

## Technical Approach

Replace the filesystem-backed `backend/clients/{client}/agents/{agent}/skills/registry.yaml` + `*.agent-skill.md` pair with three DB tables — `skill_packages` (one Qora-owned package, one package per client), `skills` (a named slot within a package, scoped to a `general` or `agent` section), and `skill_revisions` (immutable, insert-only content history) — resolved per agent through a single function that combines the Qora package's general skills, the client package's general section, and the client package's agent section for that specific agent, with a documented specificity-ordered collision rule. The existing runtime loader chain (`SkillRegistryEntry`, the `load_skill` tool's allowlist-before-access security model, the per-session cache, the webhook short-circuit) keeps its exact current shape; only the data source underneath it moves from files to the DB, mirroring the "keep the contract, change the backing store" precedent phase 3 (`client-integrations-secrets`) already established for CRM config.

## Architecture Decisions

| Decision | Choice | Alternatives Rejected | Rationale |
|----------|--------|------------------------|-----------|
| **P4-D1 — Three-table hierarchy, immutable revisions reusing the generic helpers** | `skill_packages(id, owner_type qora\|client, client_id nullable FK, name, created_at, updated_at)`; `skills(id, package_id FK, slug, section general\|agent, agent_id nullable FK, active_revision_id FK)` with `unique(package_id, slug, agent_id)`; `skill_revisions(id, skill_id FK, revision_number, content_md, filler_text, trigger_hint, description, source import\|api\|rollback, created_by, created_at, note)`, immutable — no `UPDATE`/`DELETE` path. Rollback is implemented by reusing `revisions_service.py`'s generic private helpers (`_create_revision`/`_get_revision`/`_list_revisions`/`_activate_revision`/`_rollback_to_revision`), parameterized for `SkillRevision` exactly as `analysis-profiles` (phase 5) added `ClientAnalysisProfileRevision` as a third owner table to the same reuse pattern — this phase adds a fourth. | (a) A single flat `skills` table with a `content_md` column directly, mutated in place (phase 3's `client_integrations` pattern). (b) A two-table design collapsing `skill_packages` and `skills` into one table with an `owner_type`/`section` composite key. | (a) is rejected because skill content is exactly the kind of multi-line, LLM-facing behavioral text where "what was the knowledge during this call" matters for debugging a live conversation — the same reasoning phase 3 itself used to justify NOT revisioning `client_integrations` (low-blast-radius single-value config) cuts the other way here: skill content IS the thing an operator will want to roll back after a bad edit breaks a call, not a rare single-field tweak. (b) is rejected because collapsing packages and skills loses the clean `unique(package_id, slug, agent_id)` constraint and makes the Qora-vs-client ownership check a conditional on a shared table's columns instead of a join — three tables mirrors the proven 1a/1b/P5 revision-table shape (owner table → revision table) with one extra level (`skill_packages` → `skills`) needed specifically because a package contains MULTIPLE named skills, unlike the single-row-per-client shape `client_analysis_profile_revisions` used. |
| **P4-D2 — Resolution order: Qora general + client general + client agent-section; agent > client-general > Qora on collision** | `resolve_agent_skills(client_id, agent_slug)` returns the union of: (1) the Qora package's `general`-section skills, (2) that client's package's `general`-section skills, (3) that client's package's `agent`-section skills scoped to `agent_id`. When the same `slug` appears in more than one source, the most specific source wins: an agent-section entry beats a client-general entry, which beats a Qora entry; the dropped lower-priority entry is logged at `WARNING`, never silently discarded without a trace. | (a) No collision resolution — reject any registration that would collide. (b) Qora-only overrides everything (Qora wins ties). (c) Merge collision fields (e.g. take `description` from one source, `trigger_hint` from another). | (a) is rejected because it turns an authoring-time convenience problem (a client wants to override a Qora-provided skill's content for one specific agent) into a hard validation error, defeating the entire point of a layered package system — the roadmap explicitly names "per-agent sections" as the phase 4 goal, which implies agent-level override is expected, not forbidden. (b) is rejected because it inverts the obvious intent: a client or agent-specific skill exists precisely to customize or replace a Qora default for that client/agent, so the MORE specific source must win, exactly mirroring `agent-config-inheritance`'s (phase 1b) own Standard→Client→Agent specificity ordering for scalar config fields — this phase applies the same specificity principle to a list-of-records shape instead of a scalar. (c) is rejected as needless complexity: a skill's fields (content, filler text, trigger hint, description) describe ONE coherent unit of knowledge: splitting them across sources on collision would produce a skill whose own trigger hint describes different content than what actually loads — all-or-nothing replacement per the specificity order is the only shape that keeps a skill internally consistent. |
| **P4-D3 — Runtime keeps `SkillRegistryEntry`/`load_skill` contract unchanged; session-scoped cache keyed by (agent_id, max contributing revision ids), invalidated on write, never a DB round trip per turn** | The DB-backed resolver returns the exact same `SkillRegistryEntry` dataclass (`name`, `description`, `trigger_hint`, `filler_text`) `load_skill_registry()` returns today; `handle_load_skill()`'s allowlist-before-access check and path-separator rejection carry over conceptually, now guarding a DB slug lookup instead of a filesystem path. The resolved set and its contents are loaded once per session (same cost profile as today's one-time file reads at session start) and cached in-process, keyed by `(agent_id, tuple of each contributing skill's active_revision_id)` so a write to any contributing skill produces a different cache key without requiring an explicit invalidation call from every write path — an API write naturally changes `active_revision_id`, which naturally changes the key, which naturally misses the old cache entry. | (a) Cache by `(client_id, agent_slug)` only, with explicit `.invalidate()` calls from every write endpoint (phase 3's `IntegrationStore` pattern). (b) No cache — resolve from the DB on every `load_skill` tool call. | (a) is a viable alternative but is REJECTED in favor of revision-id-keying specifically because skill resolution spans THREE sources (Qora package, client general, client agent-section) — an explicit-invalidation design would require every one of the three write paths to correctly invalidate every client/agent combination that could be affected (a Qora-package edit must invalidate every client's cache, not just one), which is a wider, easier-to-get-wrong invalidation surface than phase 3's single-client `IntegrationStore.invalidate(client_id)`. Keying by the contributing revision ids means a stale cache entry is a correctness impossibility by construction — the key itself changes the instant any contributing skill's active revision changes — at the cost of the cache being per-session rather than cross-session (acceptable: the resolved set is loaded once per session already, matching today's one-time file-read cost; this is not a new per-turn cost). (b) reintroduces exactly the per-turn-cost regression phase 3's `IntegrationStore` design explicitly rejected for the identical reason — a DB round trip on every voice turn is strictly worse than today's zero-cost in-memory file read from session start. |
| **P4-D4 — One-time import migration: inline parsing, idempotent, no filesystem deletion in this phase** | Migration `20261003_0026` reads every `backend/clients/*/agents/*/skills/registry.yaml` and its referenced `*.agent-skill.md` files inline (`yaml.safe_load`, plain file reads — no `app.*` import, house pattern already used by phase 3's `crm.yaml` import and phase 5's catalog seed), creates each client's package if it does not already exist, and inserts one `skills` row per registry entry in the `agent` section for that agent, seeding revision 1 with the file's `content_md`/`filler_text`/`trigger_hint`/`description`. Idempotency is enforced by checking for an existing `(package_id, slug, agent_id)` row before insert — a re-run against an already-imported DB is a no-op. The filesystem files are NOT deleted by this migration or this phase; deletion is deferred to a later release, after production has run the import, exactly matching phase 3's `crm.yaml` deferred-deletion rule. | (a) Delete the filesystem files as part of this same change, once the runtime cutover (task 4) lands. (b) Import secrets/content lazily on first read instead of via a migration. | (a) is rejected for the identical deploy-safety reason phase 3 gave for keeping `crm.yaml` on disk until a later release: deleting the files in the SAME change that introduces the DB-backed read path removes the filesystem fallback an operator would want if the migration or the runtime cutover has an undiscovered bug in production — keeping the files as inert, unread legacy artifacts for one more release is a near-zero-cost safety margin. (b) is rejected because a migration is the house-confirmed, deterministic, auditable way every prior phase (1a's Standard seed, 1b's revision seed, P3's `crm.yaml` import, P5's catalog seed) has populated a new revisioned table from existing filesystem/code data — lazy import-on-read would make the DB's state depend on runtime access patterns (a never-called agent never gets imported) rather than a single, verifiable migration step with a golden-regression test. |
| **P4-D5 — API: CRUD for packages/skills, `PUT` content creates a new revision, `GET` revisions, `POST` rollback; tenant-scoped; no admin UI this phase** | `backend/app/skills/router.py` exposes package/skill CRUD, `PUT /.../skills/{skill_id}/content` (creates a new revision, never mutates an existing one), `GET /.../skills/{skill_id}/revisions`, `POST /.../skills/{skill_id}/rollback`. Access control: a client can manage only its own package (`require_client_access`, matching every prior client-scoped router's dependency wiring); the Qora package is superadmin-only. No admin UI ships in this phase — the admin redesign is explicitly the user's own later, separate work. | (a) Build the admin editor UI in this phase, since skills are more operator-facing than CRM secrets. (b) Expose a single combined `PUT` endpoint that both edits content and activates it, skipping the separate revision-then-activate step phase 1a/1b/P3/P5 all use. | (a) is rejected because it was explicitly named out of scope by the task brief ("the user owns the admin redesign") and because every prior phase in this series (P3, P5) shipped API-only with the UI deferred — building a UI here would be the first phase to break that established precedent for no stated reason. (b) is rejected because `PUT` content implicitly activating the new revision IS the chosen behavior (matching `create_agent_config_revision`'s existing activate-on-create pattern in `revisions_service.py`) — a genuinely SEPARATE create-then-activate two-step (where a revision could exist without being active) was considered but rejected as unneeded complexity: no phase in this series has a "draft, not yet active" revision state, and introducing one here with no stated need would be speculative scope. |

## Data Flow

```
RESOLUTION (called once per session at prompt/context build time, cached per session)
─────────────────────────────────────────────────────────────────────────────────────
resolve_agent_skills(client_id, agent_slug)
       │
       ▼
load Qora package's general-section skills (owner_type="qora")
       │
       ▼
load this client's package's general-section skills (owner_type="client", client_id=...)
       │
       ▼
load this client's package's agent-section skills scoped to this agent_id
       │
       ▼
merge by slug: for each slug present in more than one source,
    keep the most specific (agent-section > client-general > Qora),
    log a WARNING naming the dropped lower-priority source
       │
       ▼
for each surviving skill, read its active_revision's content_md/filler_text/trigger_hint/description
       │
       ▼
return list[SkillRegistryEntry]  (same shape load_skill_registry() returns today)
       │
       ▼
cache keyed by (agent_id, tuple of each contributing skill's active_revision_id)


RUNTIME load_skill TOOL CALL (unchanged contract, re-targeted source)
───────────────────────────────────────────────────────────────────────
handle_load_skill(client_id, agent_slug, skill_name, registry_entries=<resolved list from above>)
       │
       ▼
reject skill_name containing path separators / ".." (unchanged defense-in-depth check)
       │
       ▼
skill_name in {entry.name for entry in registry_entries}? ──no──► {"error": "...not found..."}
       │ yes
       ▼
look up that skill's active revision's content_md (DB read, not a filesystem read)
       │
       ▼
return {"content": content_md}


WRITE PATH — SKILL CONTENT
─────────────────────────────
PUT /clients/{client_id}/skill-packages/{package_id}/skills/{skill_id}/content   { content_md, filler_text, trigger_hint, description }
       │
       ▼
validate package ownership (client package belongs to client_id, OR Qora package + superadmin)
       │
       ▼
INSERT new skill_revisions row (revision_number = max+1, source="api")
       │
       ▼
UPDATE skills.active_revision_id → new revision's id
       │
       ▼
next resolve_agent_skills() call for any affected agent naturally misses the old cache key
    (active_revision_id changed → cache key changed → re-resolved on next session start)


ONE-TIME IMPORT MIGRATION
────────────────────────────
for each backend/clients/{client}/agents/{agent}/skills/registry.yaml:
    ensure a client package exists for {client} (create if absent)
    for each entry in registry.yaml's skills list:
        skip if a skills row already exists for (package_id, slug=entry.name, agent_id={agent}) — idempotent
        read the referenced {entry.name}.agent-skill.md file's content
        INSERT skills row (section="agent", agent_id={agent}, slug=entry.name)
        INSERT skill_revisions row (revision_number=1, content_md=<file content>,
                                     filler_text=entry.filler_text, trigger_hint=entry.trigger_hint,
                                     description=entry.description, source="import")
        UPDATE skills.active_revision_id → that revision's id
    (filesystem files are NOT deleted — deferred to a later release, P4-D4)
```

## File Changes

| File | Action | Description |
|------|--------|--------------|
| `backend/app/tenants/models.py` | Modify | `SkillPackage`, `Skill`, `SkillRevision` models |
| `backend/alembic/versions/20261003_0025_skill_packages_schema.py` | Create | `CREATE TABLE skill_packages`, `CREATE TABLE skills`, `CREATE TABLE skill_revisions`; `unique(package_id, slug, agent_id)` on `skills` |
| `backend/alembic/versions/20261003_0026_import_skill_registries.py` | Create | One-time, idempotent import of every `backend/clients/*/agents/*/skills/registry.yaml` + referenced `*.agent-skill.md` into a client package's agent-section skills, revision 1 each; no `app.*` import |
| `backend/app/skills/service.py` | Create | Package/skill/revision CRUD on `revisions_service.py`'s generic helpers; `resolve_agent_skills(client_id, agent_slug) -> list[SkillRegistryEntry]` |
| `backend/app/skills/cache.py` | Create | Per-session cache keyed by `(agent_id, tuple of contributing active_revision_id values)` |
| `backend/app/skills/router.py` | Create | Package/skill CRUD; `PUT .../content` (new revision); `GET .../revisions`; `POST .../rollback`; tenant-scoped, Qora package superadmin-only |
| `backend/app/prompts/skill_loader.py` | Modify | `load_skill_registry()` calls `resolve_agent_skills()` instead of parsing `registry.yaml`; `SkillRegistryEntry` unchanged |
| `backend/app/prompts/loader.py` | Modify | Lines 138 (`load_agent_skills()`), 164 (`load_skill_registry_entries()`) — call the DB-backed resolver |
| `backend/app/voice/context.py` | Modify | Lines 242, 259 — index/allowlist injection sources the resolved DB skill set |
| `backend/app/tools/skill_loader.py` | Modify | `handle_load_skill()` looks up `content_md` from the active revision via the resolved allowlist instead of reading a `*.agent-skill.md` file |
| `backend/app/tools/dispatcher.py` | Modify | Lines 231-246 — unchanged routing shape, sources content via the new handler |
| `backend/app/tools/registry.py` | Modify | Lines 27, 63, 81 — unchanged tool definition/filler-phrase wiring |
| `backend/app/voice/session.py` | Modify | Lines 45-49 — unchanged `loaded_skills` cache shape |
| `backend/app/voice/webhook.py` | Modify | Lines 400-420 — unchanged short-circuit logic |
| `backend/clients/*/agents/*/skills/registry.yaml` + `*.agent-skill.md` | Unaffected (legacy, deletion deferred) | No longer read after task 4; remain on disk |

## Interfaces / Contracts

```python
# backend/app/skills/service.py
async def resolve_agent_skills(
    session: AsyncSession, client_id: str, agent_slug: str
) -> list[SkillRegistryEntry]:
    """Qora general + client general + client agent-section, with
    agent > client-general > qora on slug collision (P4-D2). Dropped
    lower-priority entries are logged at WARNING, never silently discarded
    without a trace. Returns the same SkillRegistryEntry shape
    load_skill_registry() returns today."""


async def create_skill_revision(
    session: AsyncSession,
    skill_id: str,
    content_md: str,
    filler_text: str,
    trigger_hint: str,
    description: str,
    source: Literal["import", "api", "rollback"],
    created_by: str,
    note: str | None = None,
) -> SkillRevision:
    """Inserts a new, immutable revision and activates it on the owning
    skill. Never mutates an existing revision row."""


async def rollback_skill(
    session: AsyncSession, skill_id: str, target_revision_id: str, created_by: str
) -> SkillRevision:
    """Creates a NEW revision copying target_revision_id's content; does not
    resurrect or reactivate the old row (same pattern as
    rollback_client_revision / analysis-profiles' rollback)."""
```

```python
# backend/app/skills/cache.py
class AgentSkillsCache:
    """Per-session cache. Key: (agent_id, tuple of each contributing
    skill's active_revision_id). A write that changes any contributing
    skill's active_revision_id produces a different key on the next
    resolve call — no explicit .invalidate() call required (P4-D3)."""

    async def get(
        self, session: AsyncSession, client_id: str, agent_slug: str
    ) -> list[SkillRegistryEntry]: ...
```

```python
# backend/app/tenants/models.py — new models
class SkillPackage(Base):
    __tablename__ = "skill_packages"
    id: Mapped[str]
    owner_type: Mapped[str]           # "qora" | "client"
    client_id: Mapped[str | None]     # FK clients.id, nullable (null for the Qora package)
    name: Mapped[str]
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class Skill(Base):
    __tablename__ = "skills"
    __table_args__ = (UniqueConstraint("package_id", "slug", "agent_id"),)
    id: Mapped[str]
    package_id: Mapped[str]           # FK skill_packages.id
    slug: Mapped[str]
    section: Mapped[str]              # "general" | "agent"
    agent_id: Mapped[str | None]      # FK agents.id, non-null only when section="agent"
    active_revision_id: Mapped[str | None]  # FK skill_revisions.id


class SkillRevision(Base):
    __tablename__ = "skill_revisions"
    id: Mapped[str]
    skill_id: Mapped[str]             # FK skills.id
    revision_number: Mapped[int]
    content_md: Mapped[str]
    filler_text: Mapped[str]
    trigger_hint: Mapped[str]
    description: Mapped[str]
    source: Mapped[str]               # "import" | "api" | "rollback"
    created_by: Mapped[str]
    created_at: Mapped[datetime]
    note: Mapped[str | None]
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|---------------|----------|
| Unit | `resolve_agent_skills` resolution order | Qora-only general skill resolves when no client override exists; a client-general skill with the same slug overrides the Qora one; an agent-section skill with the same slug overrides both; each collision logs a `WARNING` naming the dropped source |
| Unit | `resolve_agent_skills` returns `SkillRegistryEntry` shape | A seeded skill/revision round-trips into a `SkillRegistryEntry` with matching `name`/`description`/`trigger_hint`/`filler_text` |
| Unit | Revision immutability | `create_skill_revision` never issues an `UPDATE`/`DELETE` against an existing `skill_revisions` row; two calls produce two distinct rows with sequential `revision_number`s |
| Unit | Rollback creates a new revision, not a resurrection | Rolling back a skill at revision 2 to revision 1's content creates revision 3; revision 1's row is unchanged; `active_revision_id` points at revision 3 |
| Unit | Cache key changes on write | `.get()` after a write (which changes `active_revision_id`) returns the updated content on the next call, without an explicit invalidate call, verified via the key's revision-id component changing |
| Unit | `handle_load_skill` allowlist-before-access, re-targeted | A skill name not present in the resolved entry list is rejected before any DB content lookup; path-separator/`..` input is rejected identically to today's filesystem-path check |
| Integration | One-time import migration, idempotent | Run against a tmp DB seeded with Quintana's real `registry.yaml` fixture; assert resulting rows match; re-run the migration a second time; assert no duplicate rows are created |
| Integration | Golden regression — Quintana's `leads-agent` byte-identical | `resolve_agent_skills("quintana-seguros", "leads-agent")` after import returns entries whose `description`/`trigger_hint`/`filler_text` string-equal the current `registry.yaml` values, and whose resolved content string-equals the current `*.agent-skill.md` file contents exactly |
| Integration | No DB round trip per turn | A simulated multi-turn conversation within one session issues at most one resolution call for the session's lifetime, not one per turn (assert via a DB-call-count mock across turns) |
| Integration | Qora package is superadmin-only | A non-superadmin client-scoped request to write a Qora-package skill is rejected; the same client can write its own client-package skill without superadmin |
| Regression | Static-import guard | A source-grep-based test over `backend/app/` asserts no remaining filesystem read of `registry.yaml` or `*.agent-skill.md` exists once task 4 is complete |
| Regression | Existing loader-chain/tool/dispatcher test suites still pass | `backend/tests/.../test_skill_loader.py`, `test_loader.py` (skills portion), `test_dispatcher.py`, `test_context.py`'s skill-index assertions continue to pass against the DB-backed implementation, with fixtures adjusted to seed DB rows instead of tmp filesystem files where the test directly asserted a filesystem read (those specific assertions are updated to assert the DB-sourced value, not removed) |

## Migration / Rollout

**Staged rollout** (see tasks.md for full per-task RED/GREEN/rollback breakdown):

1. Models + schema migration — additive
2. One-time import migration — additive, idempotent; filesystem files remain the source of truth since nothing reads the DB yet
3. Service + resolution + cache — additive, nothing in the runtime loader chain calls it yet
4. Runtime cutover — the only reader-facing behavioral change; Quintana's `leads-agent` resolved registry and skill contents must be byte-identical before and after
5. API — packages/skills CRUD, content write (new revision), revisions, rollback
6. Full suites + rollout notes

**Existing-client safe path**: `quintana-seguros` is the only client with real skill content today (`leads-agent`'s two skills; `jaumpablo`'s `registry.yaml` is `skills: []`, imports to zero rows). The import migration (task 2) creates its client package and both skills automatically; no behavior change is observable to that client until task 4's cutover, which is independently verifiable via the golden regression test before and after.

## Rollback Plan

| Stage | Action | Notes |
|-------|--------|-------|
| After task 1 (models + schema migration) | `alembic downgrade -1` | No runtime code depends on any of the three tables yet |
| After task 2 (import migration) | `alembic downgrade -1`; imported rows removed | Filesystem files untouched, still the source of truth since task 4 has not cut over |
| After task 3 (service + resolution + cache) | Revert PR | Pure addition, nothing calls it yet |
| After task 4 (runtime cutover) | Revert PR | Every loader-chain reader reverts to `registry.yaml`/`*.agent-skill.md`, both still on disk — isolated because this task is never combined with another |
| After task 5 (API) | Revert PR | No runtime impact — the loader chain (task 4) does not depend on the API existing |
| After task 6 (full suites) | n/a — verification gate | Any failure blocks closing the change until fixed or explicitly triaged as pre-existing/unrelated |

## Open Questions

- [ ] Should the Qora package support more than one package instance (e.g. a "beta" Qora package for staged rollout of new skills)? Not blocking any task 1-6; `owner_type="qora"` currently implies exactly one row, revisit only if a real multi-package need appears.
- [ ] Exact logging shape for a collision-drop event (structured log fields vs. a free-text `WARNING` message) — either is sufficient for this phase's scope; a naming choice, not a blocking design decision.
- [ ] Whether `skills.agent_id` should eventually support a list of agents (a skill shared by two specific agents, neither general nor client-wide) — not requested by the roadmap's "Qora package + client package with per-agent sections" phrasing; revisit only if a real client asks for it.
