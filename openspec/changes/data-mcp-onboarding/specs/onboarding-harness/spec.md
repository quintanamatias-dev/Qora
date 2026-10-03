# onboarding-harness Specification

## Purpose

Define the behavioral contract for the declarative onboarding harness: the spec shape (and its explicit exclusion of secret fields), the shared CLI/endpoint provisioning behavior, idempotent dry-run and real-run semantics, and the verification checklist output including the manual dashboard follow-up steps the harness does not and cannot automate.

---

## Requirements

### Requirement: The Onboarding Spec Accepts No Secret Value

The onboarding spec schema MUST NOT include any field shaped to accept a credential, API key, or other secret value.

#### Scenario: An unknown field is rejected

- GIVEN an onboarding spec payload that includes a field not defined in the schema (such as an attempted `api_key`)
- WHEN the spec is parsed
- THEN parsing fails with a validation error naming the unexpected field

#### Scenario: The CRM integration portion of the spec has no credential field

- GIVEN the CRM integration section of the onboarding spec schema
- WHEN its field set is inspected
- THEN it contains only non-secret configuration fields (such as base id, table id, field mappings), and no field intended to carry a secret value

---

### Requirement: The CLI and the Admin Endpoint Share Identical Provisioning Behavior

The CLI entrypoint and the admin API endpoint MUST produce the same provisioning result for the same spec, by calling the same underlying service function.

#### Scenario: Identical specs produce identical results

- GIVEN the same onboarding spec is submitted once via the CLI and once via the admin endpoint, against the same database state
- WHEN both runs complete
- THEN the resulting entities and the verification checklist are equivalent between the two

---

### Requirement: Dry-Run Validates Without Writing Any Row

When the harness is invoked in dry-run mode, it MUST perform full validation of the spec — including checking for existing conflicting entities — without creating, updating, or deleting any row.

#### Scenario: A valid spec in dry-run mode writes nothing

- GIVEN a well-formed onboarding spec for a client and agent that do not yet exist
- WHEN the harness runs in dry-run mode
- THEN no client, agent, profile, or integration row is created
- AND the dry-run result reports what would be created

#### Scenario: A dry run detects an existing conflict

- GIVEN an onboarding spec whose client_id already exists in the database
- WHEN the harness runs in dry-run mode
- THEN the dry-run result names the conflict
- AND no row is written

---

### Requirement: A Real Run Is Idempotent Per Entity

Running the harness against a spec whose client or agent already exists MUST NOT create a duplicate record and MUST NOT raise an error. Each entity's outcome (created or already-existing) MUST be individually reported.

#### Scenario: Re-running an identical spec reports existing entities, not duplicates

- GIVEN a client and agent were already created by a prior run of a given spec
- WHEN the harness runs again with the same spec
- THEN the result reports both the client and the agent as already existing
- AND no duplicate client or agent row is created

#### Scenario: A partially completed prior run can be safely resumed

- GIVEN a prior run created the client but failed before creating the agent
- WHEN the harness runs again with the same spec
- THEN the client is reported as already existing
- AND the agent is created, completing the provisioning

---

### Requirement: An ElevenLabs Sync Is Triggered Only When the Agent Has a Linked ElevenLabs Agent ID

The harness MUST trigger an ElevenLabs configuration sync only when the agent being provisioned has an `elevenlabs_agent_id` set. It MUST NOT attempt a sync otherwise.

#### Scenario: No elevenlabs_agent_id means no sync attempt

- GIVEN an onboarding spec whose agent has no `elevenlabs_agent_id`
- WHEN the harness provisions that agent
- THEN no ElevenLabs sync call is attempted

#### Scenario: A set elevenlabs_agent_id triggers the existing sync entrypoint

- GIVEN an onboarding spec whose agent has an `elevenlabs_agent_id` set
- WHEN the harness provisions that agent
- THEN the existing agent-configuration sync entrypoint is called for that agent

---

### Requirement: The Verification Checklist Names Every Automated Step and Every Remaining Manual Step

After a real run, the harness MUST return a checklist naming the outcome of every automated step it performed, and MUST list the manual, dashboard-only steps the operator must still complete, drawn from the documented setup skill.

#### Scenario: The checklist reports every automated step's outcome

- GIVEN a completed real run with a client, agent, analysis profile, and CRM integration all requested
- WHEN the verification checklist is returned
- THEN it reports the outcome of the client creation, the agent creation, the analysis profile attachment, the integration row creation, and the ElevenLabs sync attempt (if applicable)

#### Scenario: The checklist lists the manual dashboard steps it did not perform

- GIVEN any completed real run
- WHEN the verification checklist is returned
- THEN it includes the ElevenLabs-dashboard-only setup steps (agent creation, voice selection, Custom LLM URL, initiation webhook, first message, phone number resource, post-call webhook secret) as a follow-up list for the operator

#### Scenario: Effective config completeness is reported per required field

- GIVEN a completed real run
- WHEN the verification checklist evaluates whether the agent's effective configuration is complete
- THEN it reports completeness based on each required field being both present and non-empty, not merely present
