# elevenlabs-reconciler Specification

## Purpose

Define the behavioral contract for the periodic, report-only ElevenLabs configuration reconciler: the `elevenlabs_reconciliation_reports` table, the fetch-only drift-detection pass, the admin reporting/run-now API, and the removal of two long-dead legacy fallback paths (`webhook.py`'s DEPRECATED-column reads, `is_default`'s write-time enforcement and response exposure). This spec does not define `sync_agent_config`'s own save-time verification behavior (unchanged, owned by `sdd/elevenlabs-config`) — it only defines the new periodic layer that reuses that path's drift-computation logic.

---

## Requirements

### Requirement: Reconciliation Never Mutates the Live ElevenLabs Agent

A reconciliation pass MUST only read an agent's live ElevenLabs configuration. It MUST NOT send any PATCH, PUT, or POST request to ElevenLabs that would change the agent's configuration.

#### Scenario: A reconciliation run issues only GET requests

- GIVEN one or more active, ElevenLabs-linked agents exist
- WHEN a reconciliation pass runs
- THEN every HTTP call made to ElevenLabs during the pass is a GET
- AND no PATCH, PUT, or POST request is issued to any ElevenLabs agent-configuration endpoint

#### Scenario: Detected drift does not trigger automatic repair

- GIVEN a reconciliation pass detects drift for an agent
- WHEN the pass completes
- THEN the agent's live ElevenLabs configuration is unchanged
- AND repairing the drift requires a separate, explicit operator action (the existing sync endpoint)

---

### Requirement: One Agent's Failure Does Not Block Another Agent's Check

A fetch or comparison failure for one agent MUST NOT prevent any other agent's reconciliation check from completing in the same pass.

#### Scenario: A failing agent's error is isolated

- GIVEN two active, ElevenLabs-linked agents, one whose live-config fetch fails and one whose fetch succeeds
- WHEN a reconciliation pass runs
- THEN the failing agent's report has `status = "error"`
- AND the succeeding agent's report reflects its own actual drift state, unaffected by the other agent's failure

#### Scenario: An unexpected exception during one agent's check does not abort the pass

- GIVEN a reconciliation pass is processing multiple agents
- WHEN an unexpected exception occurs while processing one agent
- THEN that agent's report is marked `status = "error"`
- AND every subsequent agent in the same pass is still processed

---

### Requirement: Each Agent Has At Most One Current Reconciliation Report

Every active, ElevenLabs-linked agent MUST have at most one `elevenlabs_reconciliation_reports` row, upserted on each pass. The report MUST record `status` (`in_sync`, `drift`, or `error`), the specific drifted fields when `status = "drift"`, and the time it was checked.

#### Scenario: A repeated pass updates the same row, not a new one

- GIVEN an agent already has a reconciliation report from a prior pass
- WHEN a new reconciliation pass runs for that agent
- THEN the existing report row is updated in place
- AND no duplicate row is created for that agent

#### Scenario: Drift is reported with the specific fields that differ

- GIVEN an agent's live ElevenLabs configuration differs from Qora's projection in one or more fields
- WHEN the reconciliation pass computes drift for that agent
- THEN the report's `status` is `drift`
- AND the report names the specific field or fields that differ

#### Scenario: A matching configuration is reported in sync

- GIVEN an agent's live ElevenLabs configuration matches Qora's projection in every field that was last sent
- WHEN the reconciliation pass computes drift for that agent
- THEN the report's `status` is `in_sync`

---

### Requirement: The Reconciliation Report Is Readable and Runnable On Demand By a Superadmin

A superadmin MUST be able to retrieve the current reconciliation report for every agent, and MUST be able to trigger an immediate reconciliation pass without waiting for the next scheduled interval.

#### Scenario: A superadmin retrieves the current report

- GIVEN reconciliation reports exist for one or more agents
- WHEN a superadmin calls the reconciliation report endpoint
- THEN the response includes every agent's latest `status`, drift fields (if any), and check time

#### Scenario: A non-superadmin cannot access the reconciliation report or trigger a run

- GIVEN a caller without superadmin privileges
- WHEN that caller calls either the report endpoint or the run-now endpoint
- THEN the request is rejected

#### Scenario: A superadmin triggers an immediate pass

- GIVEN a superadmin wants fresh data without waiting for the scheduled interval
- WHEN the superadmin calls the run-now endpoint
- THEN a reconciliation pass executes immediately
- AND a subsequent report retrieval reflects that pass's results, not a stale scheduled result

---

### Requirement: Legacy DEPRECATED-Column Fallback Reads Are Removed From the Voice Webhook

The voice webhook MUST NOT read `Client.system_prompt_override` or `Client.tools_enabled` as a fallback when an agent is absent. The underlying database columns remain present and unused, pending a separate, deferred removal.

#### Scenario: No remaining read of the deprecated columns in the webhook

- GIVEN the voice webhook's request-handling code
- WHEN that code is inspected for references to `Client.system_prompt_override` or `Client.tools_enabled`
- THEN no such reference exists

#### Scenario: An active client's call is unaffected by the removal

- GIVEN a client with a resolvable, active Agent (the case for every currently active client)
- WHEN that client's call is handled by the voice webhook
- THEN the call's prompt and tool resolution is unchanged by the removal of the deprecated fallback

---

### Requirement: is_default Has No Remaining Write-Time Enforcement or Response Exposure

Creating or updating an Agent MUST NOT enforce any uniqueness constraint on `is_default`. The `AgentResponse` schema MUST NOT include an `is_default` field. The underlying database column remains present and unused.

#### Scenario: Multiple agents for the same client may each have is_default=True

- GIVEN a client has an agent with `is_default = True`
- WHEN a second agent for that client is created with `is_default = True`
- THEN the creation succeeds without any uniqueness error

#### Scenario: The agent response no longer includes is_default

- GIVEN any agent retrieval or creation response
- WHEN the response body is inspected
- THEN it does not contain an `is_default` field

#### Scenario: Agent resolution for a call is unaffected by is_default

- GIVEN a client with exactly one active agent
- WHEN that client's agent is resolved for a call
- THEN resolution succeeds based solely on active-agent count, never consulting `is_default`
