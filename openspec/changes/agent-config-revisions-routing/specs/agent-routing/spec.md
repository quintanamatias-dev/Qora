# agent-routing Specification

## Purpose

Define the behavioral contract for identifying the Qora agent on every runtime path — live calls, scheduler, recontact, the `schedule_followup` tool, outbound triggers, lead voice-context preview, and session creation — without ever reading an `is_default` flag. This spec covers agent-scoped live-call routing, legacy-route fail-closed compatibility, deprecation observability, and the removal of default-agent resolution semantics.

---

## Requirements

### Requirement: Agent-Scoped Live-Call Routing

The system MUST provide a custom-LLM route that identifies both `client_id` and `agent_id` from the URL path, so every agent belonging to a client is independently reachable regardless of how many other agents that client has.

The route MUST resolve the target agent from the path parameter, never from `is_default`. A client with multiple active agents MUST have every one of them reachable via its own path.

#### Scenario: Agent-scoped route reaches a non-default agent

- GIVEN `quintana-seguros` has two active agents, `jaumpablo` (previously the only reachable agent) and `leads-agent`
- WHEN a POST request is made to `/voice/quintana-seguros/agents/{leads_agent_id}/custom-llm/chat/completions`
- THEN the response reflects `leads-agent`'s configuration (e.g. its system prompt), not `jaumpablo`'s

#### Scenario: Agent-scoped route rejects a mismatched client/agent pair

- GIVEN an `agent_id` in the URL path that belongs to a different client than the `client_id` in the same path
- WHEN the request is made
- THEN the system returns an explicit error and does not process the request as if the agent belonged to the given client

---

### Requirement: Conversation-Initiation Agent Resolution

The conversation-initiation webhook MUST resolve the Qora agent from the ElevenLabs `agent_id` supplied in the request payload, using the existing one-to-one mapping between `agents.elevenlabs_agent_id` and the ElevenLabs agent, never by resolving a client's default agent.

When the payload does not supply an `agent_id`, the system MUST fall back to the legacy single-active-agent resolution path (see Legacy Route Compatibility below), not to an unconditional default-agent lookup.

#### Scenario: Initiation webhook resolves the correct agent from the EL agent_id

- GIVEN a conversation-initiation payload carrying a known ElevenLabs `agent_id` that maps to `leads-agent`
- WHEN the webhook processes the request
- THEN the returned `dynamic_variables.agent_name` reflects `leads-agent`, not the client's previously-default agent

#### Scenario: Initiation webhook without an agent_id falls back safely

- GIVEN a conversation-initiation payload with no `agent_id` field
- AND the resolved client has exactly one active agent
- WHEN the webhook processes the request
- THEN the single active agent is resolved and the request succeeds

- GIVEN a conversation-initiation payload with no `agent_id` field
- AND the resolved client has zero or more than one active agent
- WHEN the webhook processes the request
- THEN the system returns an explicit error identifying the ambiguity, not a silently-picked agent

---

### Requirement: Legacy Route Compatibility — Fail Closed

Legacy client-keyed routes (`/custom-llm`, `/{client_id}/custom-llm/chat/completions`, and any other call site that previously resolved an agent via `is_default`) MUST continue to function only when the resolved client has exactly one active agent. When the client has zero active agents or more than one active agent, the system MUST return an explicit error and MUST NOT silently select an agent.

#### Scenario: Legacy route succeeds for a single-active-agent client

- GIVEN `qora-demo` has exactly one active agent
- WHEN a request is made to the legacy client-keyed route
- THEN the request succeeds using that single active agent

#### Scenario: Legacy route fails closed for a multi-agent client

- GIVEN `quintana-seguros` has two active agents
- WHEN a request is made to the legacy client-keyed route without an explicit `agent_id`
- THEN the system returns an explicit error and does not process the request against either agent

#### Scenario: Legacy route fails closed when a client has no active agents

- GIVEN a client with zero active agents (all deactivated)
- WHEN a request is made to the legacy client-keyed route
- THEN the system returns an explicit error

---

### Requirement: Legacy Route Deprecation Observability

Every successful legacy-route request MUST be logged with a deprecation marker identifying the route as deprecated and pointing to the agent-scoped equivalent, so remaining legacy traffic is observable ahead of its removal in a later cleanup slice.

#### Scenario: Legacy route hit is logged with a migration hint

- GIVEN a successful request on a legacy client-keyed route
- WHEN the request completes
- THEN a structured log entry is emitted identifying the legacy route as deprecated and naming the recommended agent-scoped route

---

### Requirement: Explicit Agent Identification on Every Call-Creating Path

Call session creation, scheduled-call creation, the `schedule_followup` tool, the outbound trigger, and the lead voice-context preview endpoint MUST each accept or resolve an explicit `agent_id` and MUST NOT resolve an agent via `is_default`.

When `agent_id` is omitted on a call-creating path, the system MUST either (a) inherit it from an existing related record (e.g. a scheduled call's source session) or (b) apply the Legacy Route Compatibility fail-closed rule — never an unconditional default-agent lookup.

#### Scenario: Session creation inherits an explicit agent_id

- GIVEN an explicit `agent_id` is provided to session creation
- WHEN the session is created
- THEN the session's `agent_id` matches the provided value exactly

#### Scenario: Session creation without agent_id fails closed for a multi-agent client

- GIVEN a client with two active agents
- WHEN session creation is requested without an `agent_id`
- THEN the system raises an explicit error and does not create a session with a guessed agent

#### Scenario: Auto-scheduled follow-up inherits the source session's agent

- GIVEN a call session with a known `agent_id`
- WHEN an auto-scheduled follow-up call is created from that session
- THEN the scheduled call's `agent_id` matches the source session's `agent_id`

#### Scenario: Outbound trigger requires an explicit agent_id

- GIVEN an outbound call trigger request with no `agent_id` field
- WHEN the request is validated
- THEN the system rejects the request as invalid, requiring an explicit `agent_id`

#### Scenario: Lead voice-context preview requires an explicit agent_id

- GIVEN a lead voice-context preview request with no `agent_id` parameter
- WHEN the request is validated
- THEN the system rejects the request as invalid, requiring an explicit `agent_id`

---

### Requirement: Removal of Default-Agent Resolution Semantics

`get_default_agent` and `set_default_agent` MUST NOT exist in the active codebase after this capability is fully implemented. No runtime path SHALL read or write an `is_default` flag to resolve or assign "the" agent for a client.

#### Scenario: Default-agent functions are fully removed

- WHEN the codebase is searched for `get_default_agent` or `set_default_agent`
- THEN no results are found under `backend/app`

#### Scenario: Deactivation guard no longer depends on is_default

- GIVEN a client has two active agents, neither designated `is_default`
- WHEN one of the two agents is deactivated
- THEN the deactivation succeeds (the client still has one active agent remaining)

- GIVEN a client has exactly one active agent
- WHEN that agent's deactivation is attempted
- THEN the system blocks the deactivation, because it is the client's last remaining active agent — not because of any `is_default` flag

#### Scenario: Admin UI no longer offers a default-agent action

- GIVEN the agents admin panel is rendered for a client with multiple agents
- WHEN the panel is inspected
- THEN no "Make default" action or "Default" badge is present for any agent
