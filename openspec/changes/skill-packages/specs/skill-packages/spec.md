# skill-packages Specification

## Purpose

Define the behavioral contract for DB-backed, revisioned voice-agent skills: the `skill_packages`/`skills`/`skill_revisions` table hierarchy, the Qora-package/client-package(general + agent-section) resolution order and its collision rule, the one-time idempotent import from existing `registry.yaml`/`*.agent-skill.md` files, the unchanged `SkillRegistryEntry`/`load_skill` runtime contract, the per-session resolved-skill-set cache, and the package/skill/revision CRUD + rollback API. This spec does not define `load_skill_force_injection`'s inheritance behavior (unchanged, owned by `tenants/field_policy.py`/`config_standard.py`) or any admin UI for package/skill editing.

---

## Requirements

### Requirement: Every Skill Has An Immutable Revision History

Every row in `skill_revisions` MUST be immutable once created — no `UPDATE` or `DELETE` path exists on this table. Editing a skill's content MUST create a new revision and point the owning `skills` row's `active_revision_id` at it; the previous revision's row MUST remain unchanged.

#### Scenario: Writing new content creates a new revision, never mutates an existing one

- GIVEN a skill has an active revision with `revision_number = 1`
- WHEN the skill's content is updated via the write API
- THEN a new row is created with `revision_number = 2`
- AND the row for `revision_number = 1` is unchanged
- AND the skill's `active_revision_id` now points at `revision_number = 2`

#### Scenario: Rollback creates a new revision, it does not resurrect the old one

- GIVEN a skill has revisions 1 and 2, with revision 2 currently active
- WHEN a rollback to revision 1 is requested
- THEN a new revision 3 is created, with content copied from revision 1
- AND the skill's `active_revision_id` points at revision 3, not revision 1
- AND revision 1's own row is unchanged

---

### Requirement: Resolution Combines Qora, Client-General, and Client-Agent-Section Skills

Resolving one agent's effective skill set MUST combine: (1) every skill in the Qora-owned package's `general` section, (2) every skill in that agent's client package's `general` section, and (3) every skill in that agent's client package's `agent` section scoped to that specific agent. When a slug appears in more than one of these three sources, the most specific source MUST win: an agent-section entry over a client-general entry, and a client-general entry over a Qora entry. The dropped lower-priority entry MUST be logged, never silently discarded without a trace.

#### Scenario: A Qora-provided skill resolves when no client override exists

- GIVEN the Qora package has a general-section skill with slug `example-skill`
- AND the agent's client package has no skill with that slug in either section
- WHEN that agent's skill set is resolved
- THEN the resolved set includes the Qora package's `example-skill` content

#### Scenario: A client-general skill overrides a Qora skill with the same slug

- GIVEN the Qora package has a general-section skill with slug `example-skill`
- AND the agent's client package also has a general-section skill with slug `example-skill`
- WHEN that agent's skill set is resolved
- THEN the resolved set includes the client package's `example-skill` content, not the Qora package's
- AND a warning is logged naming the dropped Qora-sourced entry

#### Scenario: An agent-section skill overrides both a client-general and a Qora skill with the same slug

- GIVEN the Qora package, the client package's general section, and the client package's agent section for this agent all have a skill with slug `example-skill`
- WHEN that agent's skill set is resolved
- THEN the resolved set includes the agent-section skill's content, not the client-general or Qora content
- AND a warning is logged naming each dropped lower-priority entry

#### Scenario: An agent-section skill scoped to a different agent does not leak into this agent's resolution

- GIVEN a client package has an agent-section skill scoped to agent A
- WHEN agent B's (a different agent, same client) skill set is resolved
- THEN the resolved set does not include that agent-A-scoped skill

---

### Requirement: The `load_skill` Runtime Contract Is Unchanged

The `SkillRegistryEntry` dataclass shape (`name`, `description`, `trigger_hint`, `filler_text`) and the `load_skill` tool's JSON request/response contract MUST remain exactly as they are today. Only the data source underneath the loader chain changes from the filesystem to the database.

#### Scenario: A resolved skill produces the same entry shape as the filesystem-backed loader did

- GIVEN an agent's skill set is resolved from the database
- WHEN the resolved entries are inspected
- THEN each entry has exactly the fields `name`, `description`, `trigger_hint`, `filler_text`, matching the shape the filesystem-backed loader produced before this change

#### Scenario: A client with no configured skills resolves to an empty list

- GIVEN an agent has no contributing skills from any of the three resolution sources
- WHEN that agent's skill set is resolved
- THEN the resolved list is empty
- AND no `## Available Skills` block is injected into that agent's system prompt (matching today's "no registry.yaml" behavior)

#### Scenario: The `load_skill` tool call returns the same response shape as before

- GIVEN a skill name present in the resolved entry list
- WHEN the `load_skill` tool is called with that name
- THEN the response is `{"content": "<skill markdown>"}`, identical in shape to the filesystem-backed handler's response

---

### Requirement: `load_skill` Rejects Any Name Not In The Resolved Allowlist, Before Any Content Lookup

A skill name MUST be validated against the resolved, session-scoped allowlist before any content lookup is attempted. A name containing a path separator or a `..` component MUST be rejected before the allowlist check runs. Neither check MAY be skipped or reordered.

#### Scenario: A skill name not in the resolved allowlist is rejected

- GIVEN a resolved allowlist that does not contain the name `unknown-skill`
- WHEN the `load_skill` tool is called with `skill_name = "unknown-skill"`
- THEN the response is `{"error": "..."}` naming the available skills
- AND no content lookup of any kind is attempted

#### Scenario: A path-separator or traversal attempt is rejected before the allowlist check

- GIVEN a `load_skill` call with `skill_name` containing `/`, `\`, or `..`
- WHEN the tool handler processes the call
- THEN the response is `{"error": "..."}` rejecting the unsafe name
- AND neither the allowlist check nor any content lookup is reached

---

### Requirement: Resolution Does Not Add A Per-Turn Database Cost

The resolved skill set for a session MUST be computed at most once per session under unchanged contributing content, matching the cost profile of today's one-time file reads at session start. A write that changes a contributing skill's active revision MUST be reflected on the next resolution without requiring every write path to issue an explicit cross-client invalidation call.

#### Scenario: Multiple turns in one session reuse the same resolved skill set

- GIVEN a session has already resolved its agent's skill set once
- WHEN multiple further conversational turns occur in the same session with no intervening write to any contributing skill
- THEN no additional database resolution occurs for those turns

#### Scenario: A content write is reflected on the next resolution without an explicit invalidation call

- GIVEN a skill's content is updated via the write API, changing its active revision
- WHEN that skill's owning agent's skill set is next resolved
- THEN the resolution reflects the new content
- AND no write path was required to call an explicit per-client cache-invalidation function to achieve this

---

### Requirement: Import From Existing Files Is A One-Time, Idempotent Migration

The one-time import migration MUST read every existing `registry.yaml` and its referenced `*.agent-skill.md` files and create matching `skills`/`skill_revisions` rows in the importing client's package, scoped to the correct agent's section. Running the import a second time against an already-imported database MUST create no duplicate rows. The migration MUST NOT create any `client_secrets`-style secret, and MUST NOT import `app.*` modules.

#### Scenario: Import creates matching rows from an existing registry.yaml

- GIVEN a client has an existing `registry.yaml` with one skill entry and its referenced `*.agent-skill.md` file
- WHEN the import migration runs
- THEN a `skills` row is created in that client's package, scoped to that agent's section, with revision 1's `content_md`, `filler_text`, `trigger_hint`, and `description` matching the source files exactly

#### Scenario: Re-running the import against an already-imported database is a no-op

- GIVEN the import migration has already run once against a database
- WHEN the import migration's logic runs again against the same database state
- THEN no additional `skills` or `skill_revisions` rows are created

#### Scenario: An empty registry.yaml imports zero skill rows

- GIVEN a client's `registry.yaml` has an empty `skills` list
- WHEN the import migration runs
- THEN no `skills` rows are created for that client's agent

---

### Requirement: Quintana's `leads-agent` Skill Set Is Byte-Identical Before And After Import And Cutover

The import migration and the runtime cutover together MUST preserve Quintana Seguros's `leads-agent` skill set exactly: the same skill names, descriptions, trigger hints, filler text, and full skill content, byte for byte.

#### Scenario: Resolved registry entries match the source file's fields exactly

- GIVEN the import migration has run against a database containing Quintana Seguros's real `registry.yaml` for `leads-agent`
- WHEN `leads-agent`'s skill set is resolved
- THEN each resolved entry's `description`, `trigger_hint`, and `filler_text` string-equal the corresponding `registry.yaml` entry's values exactly

#### Scenario: Resolved skill content matches the source markdown file exactly

- GIVEN the import migration has run and the runtime cutover is complete
- WHEN the `load_skill` tool is called for one of `leads-agent`'s skills
- THEN the returned content string-equals the corresponding `*.agent-skill.md` file's content exactly

---

### Requirement: Writing A Skill Validates Package Ownership And Access Scope

A write to a client package's skill MUST be rejected unless the authenticated caller has access to that specific client. A write to the Qora-owned package MUST be rejected unless the authenticated caller is a superadmin.

#### Scenario: A client cannot write to another client's package

- GIVEN a client is authenticated with access scoped to client A only
- WHEN a write request targets client B's skill package
- THEN the request is rejected

#### Scenario: A non-superadmin cannot write to the Qora package

- GIVEN an authenticated, non-superadmin caller
- WHEN a write request targets the Qora-owned package's skill
- THEN the request is rejected

#### Scenario: A superadmin can write to the Qora package

- GIVEN an authenticated superadmin caller
- WHEN a write request targets the Qora-owned package's skill
- THEN the request succeeds and creates a new revision

#### Scenario: Any authenticated client can read the Qora package

- GIVEN an authenticated, non-superadmin caller scoped to any client
- WHEN a read request targets the Qora-owned package's skills
- THEN the request succeeds and returns the Qora package's skills

---

### Requirement: Rollback And Content-Write Requests Are Scoped To One Skill

A rollback request's target revision MUST belong to the same skill being rolled back. A content-write request MUST create its new revision under the specific skill named in the request path, never a different skill.

#### Scenario: A rollback target from a different skill is rejected

- GIVEN two distinct skills, each with their own revisions
- WHEN a rollback request for skill A names a target revision that belongs to skill B
- THEN the request is rejected, and no new revision is created

#### Scenario: A valid rollback request creates exactly one new revision under the correct skill

- GIVEN a skill has revisions 1 and 2, with revision 2 active
- WHEN a rollback to revision 1 is requested for that skill
- THEN exactly one new revision is created, under that same skill
- AND it becomes that skill's active revision
