# Delta for Demo Agent Selection

## Context

`demo-agent-selection` previously allowed the demo page to select a voice agent by fetching `elevenlabs_agent_id` from the Agent API directly. B5 auth must not break this flow. This delta specifies the updated behavior: agent context is resolved server-side via `/api/v1/demo/context`, demo API calls carry a properly scoped `AuthorizedSession` established server-side, and full pipeline write permissions are enabled within the demo scope.

## MODIFIED Requirements

### Requirement: Demo Agent Context Source

The demo page MUST retrieve agent context from the Qora backend endpoint `/api/v1/demo/context` rather than calling the Agent API directly. The backend resolves the agent's `elevenlabs_agent_id`, `client_name`, and `agent_name` using `QORA_DEMO_CLIENT_ID` and `QORA_DEMO_AGENT_ID` env vars. The demo page MUST use the returned `elevenlabs_agent_id` to initialize the ElevenLabs voice widget.

(Previously: demo page fetched `elevenlabs_agent_id` directly from the Agent API, which required direct API access and returned unscoped data.)

#### Scenario: Demo page loads agent context via server-side resolution

- GIVEN `QORA_DEMO_CLIENT_ID` and `QORA_DEMO_AGENT_ID` are configured
- WHEN the demo page loads and requests `/api/v1/demo/context`
- THEN the page receives `{ elevenlabs_agent_id, client_name, agent_name }` and uses `elevenlabs_agent_id` to initialize the voice widget

#### Scenario: Agent context resolves without exposing API key

- GIVEN the demo page fetches `/api/v1/demo/context`
- WHEN the response is received
- THEN no `Authorization` header, `QORA_API_KEY`, or admin credential appears in the request or response

#### Scenario: Demo page voice widget starts correctly

- GIVEN the demo page has received a valid `elevenlabs_agent_id` from `/api/v1/demo/context`
- WHEN the user initiates a voice session
- THEN the ElevenLabs widget initializes with the correct agent; the Qora backend establishes an `AuthorizedSession` at initiation time

### Requirement: Demo Call Auth Context and Pipeline Writes

Demo voice calls MUST carry a scoped `AuthorizedSession` established server-side at session start. This session MUST permit full voice pipeline writes (call session, transcript, captured data, post-call analysis) for the configured demo client/agent scope. The demo flow MUST NOT require the user to supply any auth credential.

(Previously: demo calls either lacked auth context or only had read-level access; full pipeline writes were not explicitly scoped or permitted.)

#### Scenario: Full pipeline write succeeds in demo session

- GIVEN a demo voice session with a valid `AuthorizedSession` for the configured demo agent
- WHEN the call completes
- THEN transcript, call session record, captured data, and post-call analysis are all written; no 403 or 401 is returned

#### Scenario: Demo session blocked from writing outside its scope

- GIVEN a demo `AuthorizedSession` scoped to demo `client_id=X`
- WHEN the session attempts to access or write data for `client_id=Y`
- THEN the system returns HTTP 403 and the operation does not execute
