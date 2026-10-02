# agent-config-revisions Specification

## Purpose

Define the behavioral contract for immutable, versioned agent configuration: the `agent_config_revisions` table, the `AgentConfigV1` schema, the one-time filesystem/DB import, the active-revision pointer, the write/rollback API, per-call revision attribution, and ElevenLabs projection sync reuse. This spec covers revision immutability, import fidelity, validation, rollback-as-new-revision, and sync status tracking.

---

## Requirements

### Requirement: Immutable Revision History

`agent_config_revisions` rows MUST NOT be updated or deleted once created. Every configuration change — whether from the API, an import, or a rollback — MUST create a new row. `revision_number` MUST be monotonically increasing per `agent_id`, starting at 1.

#### Scenario: Revisions are insert-only

- GIVEN an agent has an existing revision with `revision_number=1`
- WHEN a new configuration change is applied for that agent
- THEN a new row is created with `revision_number=2`
- AND the row with `revision_number=1` is unchanged in every field

#### Scenario: Revision numbers are monotonic per agent, independent across agents

- GIVEN two different agents each receive one configuration change
- WHEN both changes are applied
- THEN each agent's new revision has `revision_number` equal to one plus that agent's own previous highest revision number, independent of the other agent's revision count

---

### Requirement: AgentConfigV1 Schema Validation

Every revision's `config` field MUST validate against the `AgentConfigV1` Pydantic schema before being persisted. The schema MUST pin `schema_version` and MUST require `system_prompt` and `voice_id`. `goal` MUST be optional in this phase.

#### Scenario: Revision creation rejects an invalid config

- GIVEN a configuration payload missing `system_prompt`
- WHEN a revision creation is attempted with that payload
- THEN the system rejects the request with a validation error and no row is created

#### Scenario: Revision creation accepts a config without goal

- GIVEN a configuration payload with every required field except `goal`
- WHEN a revision creation is attempted with that payload
- THEN the revision is created successfully with `goal` absent or null

---

### Requirement: One-Time Import Preserves Faithful Config

The one-time import migration MUST create exactly one revision (`source=import`) per existing agent. The imported `system_prompt` MUST equal the filesystem `system-prompt.md` content when that file exists for the agent, and MUST equal the agent's `Agent.system_prompt` DB column otherwise — matching the priority already used by `render_for_agent` prior to this change. Every imported revision MUST be activated (set as the agent's `active_revision_id`) as part of the import.

#### Scenario: Import prefers the filesystem system prompt when present

- GIVEN an agent whose `clients/{client}/agents/{slug}/system-prompt.md` file exists and differs from its `Agent.system_prompt` DB column
- WHEN the import migration runs
- THEN the created revision's `system_prompt` equals the filesystem file's content, not the DB column's content

#### Scenario: Import falls back to the DB column when no file exists

- GIVEN an agent with no `system-prompt.md` file on the filesystem
- WHEN the import migration runs
- THEN the created revision's `system_prompt` equals `Agent.system_prompt`

#### Scenario: Every agent receives exactly one imported, active revision

- GIVEN a database with multiple existing agents across multiple clients
- WHEN the import migration completes
- THEN each agent has exactly one revision with `source=import`
- AND each agent's `active_revision_id` points at that imported revision

---

### Requirement: Active Revision Pointer

Each agent MUST have at most one active revision at any time, tracked via `agents.active_revision_id`. Activating a revision MUST be a single pointer update and MUST NOT modify any revision row's content.

#### Scenario: Activating a revision changes only the pointer

- GIVEN an agent with revision 1 active and revision 2 existing but inactive
- WHEN revision 2 is activated
- THEN `agents.active_revision_id` equals revision 2's id
- AND revision 1's and revision 2's `config` fields are unchanged from their creation values

---

### Requirement: Rollback Creates a New Revision

Rolling back to a prior revision MUST create a brand-new revision row copying the target revision's configuration, with `source="rollback"`, and then activate that new row. Rollback MUST NOT reactivate or mutate the original target revision row.

#### Scenario: Rollback produces a new revision with a higher number

- GIVEN an agent has revisions 1, 2, and 3, with revision 3 currently active
- WHEN a rollback to revision 1 is requested
- THEN a new revision 4 is created with `source="rollback"` and `config` equal to revision 1's `config`
- AND `agents.active_revision_id` is updated to revision 4's id
- AND revision 1's row remains unchanged, still with `revision_number=1` and `source` as it was originally created

#### Scenario: Rollback history remains traceable

- GIVEN a rollback has been performed
- WHEN the revision list for that agent is retrieved
- THEN the list includes both the original revision and the new rollback revision, in creation order, with the rollback revision's `source` field distinguishing it from an API edit or an import

---

### Requirement: Write Path Syncs to ElevenLabs

Every successful configuration write (API PATCH or rollback) that activates a new revision MUST enqueue an ElevenLabs projection sync using the existing agent-scoped sync mechanism. Sync status MUST be recorded on the activated revision.

#### Scenario: PATCH triggers exactly one sync call

- GIVEN a valid configuration PATCH request for an agent
- WHEN the request is processed
- THEN exactly one ElevenLabs sync call is made using the newly-activated revision's configuration
- AND the sync result (success or failure) is recorded on that revision

#### Scenario: Rollback also triggers a sync call

- GIVEN a rollback request that activates a new revision
- WHEN the rollback is processed
- THEN the same sync mechanism is invoked using the new revision's configuration

---

### Requirement: Per-Call Revision Attribution

Every call session created after this capability is active MUST record the `agent_config_revision_id` that was active for the resolved agent at the time the session was created.

#### Scenario: Call session records the active revision at call time

- GIVEN an agent's active revision is revision 3
- WHEN a call session is created for that agent
- THEN the call session's `agent_config_revision_id` equals revision 3's id

#### Scenario: A later revision change does not retroactively alter past call attribution

- GIVEN a call session was created while revision 3 was active, recording `agent_config_revision_id=3`
- WHEN the agent's active revision later changes to revision 4
- THEN the earlier call session's `agent_config_revision_id` remains 3

---

### Requirement: Revision API Surface

The system MUST expose: listing all revisions for an agent (newest first), retrieving one revision by id, and triggering a rollback to a specific revision. These endpoints MUST NOT expose any way to update or delete an existing revision's content.

#### Scenario: Listing revisions returns full history newest-first

- GIVEN an agent with three revisions
- WHEN the revisions list endpoint is called for that agent
- THEN all three revisions are returned ordered by `revision_number` descending

#### Scenario: No update or delete endpoint exists for revision content

- WHEN the API surface for `agent_config_revisions` is inspected
- THEN no endpoint accepts a request that would modify or remove an existing revision row's `config`, `source`, `created_by`, `created_at`, or `note` fields
