# config-inheritance Specification

## Purpose

Define the behavioral contract for three-level configuration inheritance (Qora standard → Client → Agent): the field-policy registry, the pure resolver with per-field provenance, client-level revisions (reusing 1a's `agent_config_revisions` mechanics), sparse agent overrides (`AgentConfigV2`), write-path validation for `locked` and `agent_required` fields, grandfathering of pre-existing agents, and propagation of client and standard-version changes. This spec layers on top of `agent-config-revisions` (1a) and does not redefine any of 1a's immutability, routing, or sync guarantees.

---

## Requirements

### Requirement: Exactly One Policy Per Field

Every field in `AgentConfigV1` (1a) MUST have exactly one policy in the field-policy registry: `locked`, `overridable`, `client_only`, or `agent_required`. The registry MUST be exhaustive — no field consumed by the resolver may be absent from it.

#### Scenario: Every AgentConfigV1 field has a registered policy

- GIVEN the field-policy registry
- WHEN every field name from `AgentConfigV1` (1a) is checked against the registry
- THEN each one has exactly one policy value, and no field is missing

#### Scenario: An unregistered field is rejected, not silently ignored

- GIVEN a configuration payload containing a field name absent from the field-policy registry
- WHEN a revision creation is attempted with that payload
- THEN the system rejects the request rather than silently applying or dropping the unregistered field

---

### Requirement: Pure Resolution With Per-Field Provenance

`resolve_effective_config` MUST be a pure function (no database access, no I/O) that, given the Qora standard, a client's overrides, and an agent's overrides, returns the effective value AND the provenance (`standard`, `client`, or `agent`) of every field. The same function MUST be used by the runtime context builder, the ElevenLabs projection sync, and the admin effective-config API — no consumer computes resolution independently.

#### Scenario: A locked field always resolves to the standard, regardless of overrides present

- GIVEN a field policy of `locked`
- AND a client override and an agent override are both present for that field
- WHEN the config is resolved
- THEN the resolved value equals the Qora standard's value
- AND the resolved provenance is `standard`

#### Scenario: An agent_required field always resolves to the agent's value

- GIVEN a field policy of `agent_required`
- AND the agent has set a value for that field
- WHEN the config is resolved
- THEN the resolved value equals the agent's value
- AND the resolved provenance is `agent`

#### Scenario: A client_only field resolves to the client's override when present, else the standard

- GIVEN a field policy of `client_only`
- AND the client has set an override for that field
- AND the agent has NOT set an override for that field
- WHEN the config is resolved
- THEN the resolved value equals the client's override
- AND the resolved provenance is `client`

- GIVEN a field policy of `client_only`
- AND neither the client nor the agent has set an override
- WHEN the config is resolved
- THEN the resolved value equals the Qora standard's value
- AND the resolved provenance is `standard`

#### Scenario: An overridable field resolves agent-first, then client, then standard

- GIVEN a field policy of `overridable`
- AND the agent has set an override for that field
- WHEN the config is resolved
- THEN the resolved value equals the agent's override, with provenance `agent`, regardless of whether a client override also exists

- GIVEN a field policy of `overridable`
- AND the agent has NOT set an override, but the client has
- WHEN the config is resolved
- THEN the resolved value equals the client's override, with provenance `client`

- GIVEN a field policy of `overridable`
- AND neither the client nor the agent has set an override
- WHEN the config is resolved
- THEN the resolved value equals the Qora standard's value, with provenance `standard`

#### Scenario: Resolution is deterministic and side-effect free

- GIVEN identical standard, client-override, and agent-override inputs
- WHEN `resolve_effective_config` is called multiple times with those same inputs
- THEN every call returns an identical result
- AND no database write or external call occurs as a result of calling the resolver

---

### Requirement: Client-Level Immutable Revisions

`client_config_revisions` MUST follow the same immutability contract as 1a's `agent_config_revisions`: insert-only, `revision_number` monotonically increasing per `client_id`, no update or delete path. Client config rows MUST store sparse overrides only — fields the client has explicitly set — not a full copy of the Qora standard.

#### Scenario: Client revisions are insert-only

- GIVEN a client has an existing config revision with `revision_number=1`
- WHEN a new client configuration change is applied
- THEN a new row is created with `revision_number=2`
- AND the row with `revision_number=1` is unchanged in every field

#### Scenario: Client revision content is sparse

- GIVEN a client sets an override for exactly one field (e.g. `language`)
- WHEN the client's revision is created and inspected
- THEN the revision's stored config contains only that one field
- AND does not contain every field from the Qora standard

---

### Requirement: AgentConfigV2 Sparse Overrides, V1 Frozen

Agent revisions created after this capability is active MUST use `AgentConfigV2` (`schema_version=2`), storing only fields the agent has explicitly overridden. Every pre-existing `AgentConfigV1` (`schema_version=1`) revision from 1a MUST remain readable and resolvable exactly as originally recorded; no migration converts a V1 revision into V2.

#### Scenario: A new agent revision stores only overridden fields

- GIVEN an agent whose client has set `tts_speed` via a client override
- AND the agent itself only overrides `system_prompt` and `voice_id`
- WHEN a new agent revision is created
- THEN the revision's `schema_version` is 2
- AND the revision's stored config contains only `system_prompt` and `voice_id`, not `tts_speed`

#### Scenario: A pre-existing V1 revision resolves without migration

- GIVEN an agent whose active revision is a `schema_version=1` full-snapshot revision from before this capability existed
- WHEN the config is resolved for that agent
- THEN every field present in that V1 revision resolves with provenance `agent`
- AND the V1 revision's row is not modified, converted, or replaced as a side effect of resolution

---

### Requirement: Write Validation Rejects Locked and Missing Required Fields

Any write (client-level or agent-level) that includes a value for a `locked` field MUST be rejected with an explicit error listing every offending field; no row is created. Any write creating a NEW agent revision that omits a value for an `agent_required` field MUST be rejected with an explicit error, UNLESS the agent is grandfathered for that specific field (see Grandfathering below).

#### Scenario: Writing a locked field is rejected

- GIVEN a configuration write payload (client or agent level) that includes a value for a field whose policy is `locked`
- WHEN the write is attempted
- THEN the system rejects the request with an error identifying every locked field present in the payload
- AND no revision is created

#### Scenario: A new agent revision missing a required field is rejected

- GIVEN an agent that is NOT grandfathered for any `agent_required` field
- AND a new revision payload omits `goal`
- WHEN the revision creation is attempted
- THEN the system rejects the request, identifying `goal` as missing
- AND no revision is created

#### Scenario: Creating a brand-new agent always requires every agent_required field

- GIVEN a request to create a brand-new agent (not a revision on an existing one)
- AND the request omits `voice_id`
- WHEN agent creation is attempted
- THEN the system rejects the request, identifying `voice_id` as missing
- AND no agent or revision is created

---

### Requirement: Grandfathering for Pre-Existing Agents

An agent that existed before this capability was introduced, and whose active revision lacks an `agent_required` field that did not previously exist as a concept (specifically `goal`), MUST continue to resolve and operate using its current active revision. The admin API and UI MUST mark such an agent as `"incomplete"`. Any NEW revision created for that agent MUST include the previously-missing field — grandfathering applies only to the agent's CURRENT active revision, not to future writes.

#### Scenario: A grandfathered agent's existing revision keeps working

- GIVEN an agent created before this capability existed, whose active revision has no `goal` field
- WHEN the config is resolved for that agent
- THEN resolution succeeds and produces an effective config, without requiring a `goal` value
- AND the agent is marked `"incomplete"` by the admin API

#### Scenario: A grandfathered agent's next revision must include the missing field

- GIVEN a grandfathered agent whose active revision has no `goal` field
- WHEN a new revision is created for that agent without a `goal` value
- THEN the system rejects the request, identifying `goal` as missing
- AND the grandfathered agent's EXISTING active revision is unaffected by the rejection

---

### Requirement: Client-Revision Propagation Re-Syncs Every Active Agent

Activating a new client config revision MUST trigger re-resolution and an ElevenLabs projection sync for every active agent belonging to that client, reusing the existing per-agent sync mechanism from 1a. This MUST happen automatically, without a separate explicit trigger.

#### Scenario: Activating a client revision syncs all of its active agents

- GIVEN a client has two active agents
- WHEN a new client config revision is activated
- THEN an ElevenLabs projection sync is enqueued for both active agents
- AND each agent's effective config reflects the new client-level override

---

### Requirement: Standard Version Changes Require an Explicit Re-Sync Action

A new `STANDARD_VERSION` becoming active (via code deploy) MUST NOT automatically trigger any ElevenLabs projection sync for any agent. Re-synchronizing agents against a new standard version MUST require an explicit admin action, and that action MUST only enqueue a sync for agents whose resolved effective config actually changed as a result of the new standard (drift detection), not for every agent platform-wide unconditionally.

#### Scenario: A standard version bump does not sync anyone automatically

- GIVEN a new `STANDARD_VERSION` has just become active after a deploy
- WHEN no explicit re-sync action has been taken
- THEN no ElevenLabs projection sync has been enqueued for any agent as a result of the version change alone

#### Scenario: The explicit re-sync action only syncs agents whose config actually changed

- GIVEN an explicit standard re-sync action is triggered
- AND only some agents' resolved effective config differs under the new standard compared to the old one
- WHEN the re-sync action completes
- THEN an ElevenLabs projection sync is enqueued only for the agents whose resolved config changed
- AND no sync is enqueued for agents whose resolved config is identical under both standard versions

---

### Requirement: Per-Call Attribution of Standard Version and Both Revision Levels

Every call session created after this capability is active MUST record the `standard_version` that was active, the `client_config_revision_id` that was active for the resolved agent's client, and the `agent_config_revision_id` that was active for the resolved agent — all at the time the session was created.

#### Scenario: A call session records all three resolution inputs

- GIVEN a client's active config revision is client-revision 2, an agent's active revision is agent-revision 5, and the active `STANDARD_VERSION` is `"2026.10.1"`
- WHEN a call session is created for that agent
- THEN the session's `standard_version` equals `"2026.10.1"`
- AND the session's `client_config_revision_id` equals client-revision 2's id
- AND the session's `agent_config_revision_id` equals agent-revision 5's id

#### Scenario: Later config changes do not retroactively alter past call attribution

- GIVEN a call session was created recording a specific standard version and both revision ids
- WHEN the client's active revision, the agent's active revision, or the active standard version later changes
- THEN the earlier call session's recorded `standard_version`, `client_config_revision_id`, and `agent_config_revision_id` remain unchanged
