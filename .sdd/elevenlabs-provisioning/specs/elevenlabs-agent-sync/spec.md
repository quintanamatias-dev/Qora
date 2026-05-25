# elevenlabs-agent-sync Specification

## Purpose

Defines behavior for programmatic ElevenLabs agent configuration from Qora backend.
Covers the service layer, Agent model extension, schema changes, sync-on-save, and manual re-sync endpoint.
This is a NEW capability — no prior spec exists.

---

## Requirements

### Requirement: ElevenLabsService PATCH

The system MUST provide an `ElevenLabsService` that sends a partial PATCH to ElevenLabs ConvAI agent config.
The service MUST only send `conversation_config.turn.soft_timeout_config` — never a full agent body.
The service MUST authenticate via `xi-api-key` header using the value from `Settings.elevenlabs_api_key`.
The service MUST enforce a 10-second request timeout.
The service MUST retry exactly once on 5xx responses before marking the result as failed.
The service MUST log structured errors on failure (including HTTP status and agent_id) and MUST NOT raise.
The service MUST return a `SyncResult` with outcome in `{synced, skipped, error}` and an optional `error_detail`.
The service MUST return `skipped` without making any HTTP call when `soft_timeout_seconds` is None.
The service MUST return `skipped` without making any HTTP call when `elevenlabs_agent_id` is None.

#### Scenario: Happy path PATCH

- GIVEN an agent with `soft_timeout_seconds=3.0`, `soft_timeout_message="Mmm..."`, `soft_timeout_use_llm=False`, and `elevenlabs_agent_id="el-abc"`
- WHEN `ElevenLabsService.sync_soft_timeout(agent)` is called
- THEN a PATCH to `https://api.elevenlabs.io/v1/convai/agents/el-abc` is sent
- AND the body contains only `{"conversation_config": {"turn": {"soft_timeout_config": {"enabled": true, "timeout_secs": 3.0, "message": "Mmm...", "use_llm": false}}}}`
- AND the result outcome is `"synced"`

#### Scenario: 5xx retry succeeds on second attempt

- GIVEN the ElevenLabs API returns 503 on the first call and 200 on the second
- WHEN `sync_soft_timeout` is called
- THEN the service retries once
- AND the result outcome is `"synced"`

#### Scenario: 5xx on both attempts

- GIVEN the ElevenLabs API returns 503 on both attempts
- WHEN `sync_soft_timeout` is called
- THEN the structured error is logged with `http_status=503` and `elevenlabs_agent_id`
- AND the result outcome is `"error"`
- AND no exception is raised to the caller

#### Scenario: No elevenlabs_agent_id — skip silently

- GIVEN an agent with `elevenlabs_agent_id=None` and `soft_timeout_seconds=3.0`
- WHEN `sync_soft_timeout` is called
- THEN no HTTP call is made
- AND the result outcome is `"skipped"`

#### Scenario: All soft timeout fields are None — skip

- GIVEN an agent with `soft_timeout_seconds=None`, `soft_timeout_message=None`, `soft_timeout_use_llm=None`
- WHEN `sync_soft_timeout` is called
- THEN no HTTP call is made
- AND the result outcome is `"skipped"`

#### Scenario: 10-second timeout enforced

- GIVEN the ElevenLabs API does not respond within 10 seconds
- WHEN `sync_soft_timeout` is called
- THEN the request times out
- AND the structured error is logged
- AND the result outcome is `"error"`

---

### Requirement: Agent Model — Soft Timeout Columns

The `Agent` model MUST add 5 nullable columns with `DEFAULT NULL`:
`soft_timeout_seconds REAL`, `soft_timeout_message TEXT`, `soft_timeout_use_llm INTEGER`,
`elevenlabs_sync_status TEXT`, `elevenlabs_last_synced_at DATETIME`.
NULL values MUST be treated as "use ElevenLabs dashboard defaults" — no PATCH is sent.
Existing agents with all new columns NULL MUST behave identically to before this change.
`soft_timeout_seconds` MUST be validated in schema at `[0.5, 8.0]` when provided.

#### Scenario: Existing agent row unaffected

- GIVEN an agent row created before this change (all 5 columns absent/NULL)
- WHEN the agent is loaded by the ORM
- THEN no error occurs
- AND the agent response omits or returns null for all 5 new fields

#### Scenario: Soft timeout persisted

- GIVEN `AgentCreate` with `soft_timeout_seconds=2.5`
- WHEN the agent is created
- THEN the DB row has `soft_timeout_seconds=2.5`

#### Scenario: Out-of-range timeout rejected

- GIVEN `AgentCreate` with `soft_timeout_seconds=0.1`
- WHEN the request is validated
- THEN a 422 is returned

---

### Requirement: Agent Schemas — Soft Timeout Fields

`AgentCreate` MUST add: `soft_timeout_seconds: float | None = None`, `soft_timeout_message: str | None = None`, `soft_timeout_use_llm: bool | None = None`.
`AgentUpdate` MUST add the same three fields, all optional.
`AgentResponse` MUST add all 5 new fields (`soft_timeout_*` + `elevenlabs_sync_status` + `elevenlabs_last_synced_at`), all nullable with `None` as default.

#### Scenario: Response includes sync status

- GIVEN an agent with `elevenlabs_sync_status="synced"` and a `elevenlabs_last_synced_at` timestamp
- WHEN `GET /api/v1/clients/{client_id}/agents/{agent_id}` is called
- THEN the response body includes `"elevenlabs_sync_status": "synced"` and the ISO timestamp

---

### Requirement: DDL Migration — ADD COLUMN IF NOT EXISTS

`_ensure_startup_schema_compat` in `main.py` MUST add all 5 new agent columns using `ALTER TABLE agents ADD COLUMN ... DEFAULT NULL` when absent.
The migration MUST use the same pattern as existing columns (`PRAGMA table_info(agents)` → `if col not in agent_columns`).
The migration MUST be idempotent — running startup twice MUST NOT error.

#### Scenario: Fresh DB startup adds columns

- GIVEN a DB without the 5 new columns
- WHEN the application starts
- THEN all 5 columns are added
- AND a `startup_schema_compat_added` log line is emitted for each

#### Scenario: Columns already exist — no-op

- GIVEN a DB with all 5 new columns already present
- WHEN the application starts
- THEN no ALTER TABLE is executed

---

### Requirement: Sync-on-Save (Fire-and-Forget)

After a successful DB commit on agent create or update, the router MUST trigger sync via `asyncio.create_task(el_service.sync_soft_timeout(agent))`.
The agent save MUST complete and return a response before sync completes.
Sync failure MUST NOT roll back or fail the agent save.
When sync completes with `"synced"`, the router MUST update `elevenlabs_sync_status="synced"` and `elevenlabs_last_synced_at=utcnow()` on the agent row.
When sync completes with `"error"`, the router MUST update `elevenlabs_sync_status="error"` on the agent row.
When sync completes with `"skipped"`, no status update is required.

#### Scenario: Create agent, sync succeeds

- GIVEN `AgentCreate` with `soft_timeout_seconds=3.0` and a valid `elevenlabs_agent_id`
- WHEN `POST /api/v1/clients/{client_id}/agents/` is called
- THEN the agent is saved and 201 is returned immediately
- AND asynchronously, ElevenLabs is PATCHed
- AND `elevenlabs_sync_status` is updated to `"synced"`

#### Scenario: Update agent, EL API down — save still succeeds

- GIVEN `AgentUpdate` with `soft_timeout_seconds=4.0` and ElevenLabs API returning 503
- WHEN `PATCH /api/v1/clients/{client_id}/agents/{agent_id}` is called
- THEN 200 is returned with the updated agent
- AND `elevenlabs_sync_status` is set to `"error"` in the background

#### Scenario: No soft timeout fields — no sync triggered

- GIVEN `AgentCreate` with no soft timeout fields set (all None)
- WHEN the agent is created
- THEN no ElevenLabs PATCH is attempted
- AND `elevenlabs_sync_status` remains NULL

#### Scenario: Concurrent saves do not corrupt state

- GIVEN two concurrent `PATCH` requests updating the same agent's soft timeout
- WHEN both commits complete
- THEN each fires its own independent `asyncio.create_task`
- AND neither task cancels or overwrites the other mid-flight

---

### Requirement: Manual Re-Sync Endpoint

The system MUST expose `POST /api/v1/clients/{client_id}/agents/{agent_slug}/sync-elevenlabs`.
The endpoint MUST call `ElevenLabsService.sync_soft_timeout(agent)` synchronously (await, not fire-and-forget).
The endpoint MUST update `elevenlabs_sync_status` and `elevenlabs_last_synced_at` based on the result.
The endpoint MUST return `{"sync_status": "<outcome>", "synced_at": "<iso-timestamp or null>"}`.
The endpoint MUST return 404 if the agent or client does not exist.

#### Scenario: Re-sync after auto-sync error

- GIVEN an agent with `elevenlabs_sync_status="error"` and a recovered ElevenLabs API
- WHEN `POST .../sync-elevenlabs` is called
- THEN ElevenLabs is PATCHed successfully
- AND the response is `{"sync_status": "synced", "synced_at": "<timestamp>"}`
- AND the DB is updated

#### Scenario: Re-sync with no elevenlabs_agent_id

- GIVEN an agent with `elevenlabs_agent_id=None`
- WHEN `POST .../sync-elevenlabs` is called
- THEN the result is `{"sync_status": "skipped", "synced_at": null}`
- AND no HTTP call is made to ElevenLabs

#### Scenario: Agent not found

- GIVEN a non-existent `agent_slug`
- WHEN `POST .../sync-elevenlabs` is called
- THEN 404 is returned

---

### Requirement: Per-Conversation Override (Optional / Future)

> **Status: OPTIONAL — MAY be implemented now or deferred.**

The WebSocket conversation init payload MAY include `conversation_config_override.turn.soft_timeout_config.message` to override the soft timeout message for a single conversation.
This REQUIRES `platform_settings.overrides.conversation_config_override.turn.soft_timeout_config.message` to be enabled on the ElevenLabs agent (one-time dashboard action per agent).
The override MUST NOT cause a WebSocket error if the ElevenLabs agent does not have overrides enabled.

#### Scenario: Per-conversation message override sent

- GIVEN an agent with `soft_timeout_message="Mmm..."` and overrides enabled in EL dashboard
- WHEN a WebSocket conversation is initiated with a caller-specific filler message
- THEN the WebSocket init payload includes `conversation_config_override.turn.soft_timeout_config.message`
- AND ElevenLabs uses the override message for that conversation only

#### Scenario: Overrides not enabled — no error

- GIVEN an agent without override permissions in ElevenLabs
- WHEN the WebSocket init includes a `soft_timeout_config` override
- THEN ElevenLabs silently ignores the override
- AND the conversation proceeds normally
