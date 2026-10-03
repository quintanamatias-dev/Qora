# data-mcp Specification

## Purpose

Define the behavioral contract for the read-only MCP server exposing Qora's internal data (clients, agents, leads, calls) to internal AI callers over stdio: the tool set, the never-secrets guarantee, the explicit-client_id requirement for tenant-scoped data, and output size limits. This spec does not define any write capability — the server has none in this phase.

---

## Requirements

### Requirement: The MCP Server Exposes Only Read Tools

Every tool registered on the MCP server MUST call a read-only service-layer function. No tool MUST create, update, or delete any record.

#### Scenario: No registered tool mutates data

- GIVEN the full set of tools registered on the MCP server
- WHEN each tool's underlying service-layer call is inspected
- THEN none of them performs an insert, update, or delete

#### Scenario: Calling a tool twice produces the same result

- GIVEN any tool is called with the same arguments twice in a row
- WHEN the two calls' results are compared
- THEN they are identical, confirming the first call caused no state change

---

### Requirement: No Tool Response Ever Contains a Secret

No tool's response MUST include a `client_secrets` ciphertext, a raw API key, a webhook secret, or any other credential value, at any nesting level of the response.

#### Scenario: get_agent's effective config never includes a secret field

- GIVEN an agent whose client has a configured CRM integration with a stored secret
- WHEN `get_agent` is called for that agent
- THEN the response's effective-config fields never include the secret's value or its ciphertext

#### Scenario: A future tool addition is checked against the same guarantee

- GIVEN a new tool is added to the server after this spec is implemented
- WHEN that tool is registered
- THEN the same never-secrets check applies to its response shape before it can be considered compliant

---

### Requirement: Tenant-Scoped Data Tools Require an Explicit client_id

Every tool that reads lead or call data MUST require `client_id` as a non-optional parameter. No tool MUST enumerate leads or calls across multiple clients in a single call.

#### Scenario: A lead or call tool rejects a call missing client_id

- GIVEN a call to `list_leads`, `get_lead`, `list_calls`, or `get_call`
- WHEN that call omits `client_id`
- THEN the call is rejected before any database query executes

#### Scenario: A lead or call tool scopes results to exactly one client

- GIVEN a valid `client_id` is provided to `list_leads` or `list_calls`
- WHEN the tool returns results
- THEN every returned record belongs to that one client, never to any other client

#### Scenario: Client and agent identity tools are the only cross-client listings

- GIVEN `list_clients` or `list_agents` is called
- WHEN the response is inspected
- THEN it contains only client or agent identity and configuration shape, never lead or call records

---

### Requirement: Every List Tool Has a Bounded Output Size

Every tool that returns a collection MUST apply pagination with a documented default and a hard maximum page size. Requesting a page size above the maximum MUST be capped, not honored as requested.

#### Scenario: A page size above the maximum is capped

- GIVEN a list tool is called with a requested page size larger than the documented maximum
- WHEN the tool returns results
- THEN the number of returned records does not exceed the documented maximum

#### Scenario: An unspecified page size uses the documented default

- GIVEN a list tool is called without specifying a page size
- WHEN the tool returns results
- THEN the number of returned records does not exceed the documented default

---

### Requirement: get_agent Reports Effective Config With Provenance

`get_agent` MUST return, for each resolved configuration field, which configuration layer (agent override, client default, or Qora standard) that field's value came from.

#### Scenario: An overridden field reports the agent layer

- GIVEN an agent with a field explicitly overridden at the agent level
- WHEN `get_agent` is called for that agent
- THEN that field's provenance is reported as the agent layer

#### Scenario: An inherited field reports its actual source layer

- GIVEN an agent with a field not overridden at the agent level, inherited from the client default or the Qora standard
- WHEN `get_agent` is called for that agent
- THEN that field's provenance is reported as whichever layer it actually resolved from, not the agent layer
