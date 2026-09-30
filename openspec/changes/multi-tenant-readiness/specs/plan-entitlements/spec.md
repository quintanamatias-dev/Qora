# Plan Entitlements Specification

## Purpose

Each client has a plan that determines which product features it can use and
hard usage limits that protect Qora's cost exposure. Plans are defined in code;
per-client overrides are operational data.

## Requirements

### Requirement: Plan Resolution

The system MUST resolve a client's effective entitlements as the plan defaults
merged with the client's overrides. An unknown plan MUST resolve to the
`starter` plan.

#### Scenario: Override enables a feature missing from the plan

- GIVEN a client on `starter` with override `features.auto_dialer = true`
- WHEN entitlements are resolved
- THEN `auto_dialer` is enabled and all other values match `starter`

#### Scenario: Existing clients keep current behaviour

- GIVEN a client created before this change
- WHEN the migration runs
- THEN its plan is `pilot` and every feature is enabled with no limits

### Requirement: Feature Gating

Routes that belong to a feature MUST return HTTP 403 with
`error = feature_not_in_plan` when the client's plan does not include it.

#### Scenario: Analytics disabled

- GIVEN a client whose entitlements disable `analytics`
- WHEN `GET /api/v1/analytics/{client_id}/overview` is requested
- THEN the response is 403 and no analytics query runs

### Requirement: Outbound Usage Limits

Before creating a call session, outbound dialing MUST verify the feature for
the dial type (`outbound_calls` for manual, `auto_dialer` for scheduled) and
the `max_concurrent_calls`, `max_monthly_calls`, and `max_monthly_minutes`
limits. A blocked dial MUST NOT create a call session or contact the provider.

#### Scenario: Monthly minutes exhausted

- GIVEN a client with `max_monthly_minutes = 200` and 200 minutes used this month
- WHEN a manual call is triggered
- THEN the response is 429 with `plan_limit_reached` and no call session exists

#### Scenario: Auto-dialer row blocked by plan

- GIVEN a due scheduled call for a client without `auto_dialer`
- WHEN the dialer claims it
- THEN the row becomes `failed` and the log records `failure_code = plan_feature_disabled`

#### Scenario: Inbound is never blocked

- GIVEN a client over its monthly minutes
- WHEN an inbound call initiates
- THEN the call proceeds normally

### Requirement: Agent Limit

Creating an agent MUST fail with 403 `plan_limit_reached` when the client
already has `max_agents` active agents.

### Requirement: Entitlements API

`GET /clients/{id}/entitlements` MUST return plan, effective features, limits,
current-month usage, and raw overrides to any principal with access to the
client. `PUT` MUST be superadmin-only and MUST reject unknown feature or limit
keys with 422.
