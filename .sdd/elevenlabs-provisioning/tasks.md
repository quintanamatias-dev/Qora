# Tasks: ElevenLabs Agent Provisioning — Phase 1 Soft Timeout

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 700-900 total |
| 400-line budget risk | High |
| 800-line review budget risk | Medium |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 service+schema+DDL → PR 2 router sync+endpoint+integration tests |
| Delivery strategy | auto-forecast |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Service foundation, model/schema columns, DDL compat, unit tests | PR 1 | Standalone; proves PATCH contract and persistence shape |
| 2 | Save-trigger sync, manual re-sync endpoint, integration tests | PR 2 | Depends on PR 1; verifies fire-and-forget and status updates |

## Phase 1: Service Foundation (RED → GREEN)

- [x] 1.1 RED: create `backend/tests/unit/elevenlabs/test_service.py` for skipped cases, exact PATCH body, `xi-api-key`, 10s timeout, one 5xx retry, and no-raise error logging with respx.
- [x] 1.2 GREEN: create `backend/app/elevenlabs/__init__.py` and `backend/app/elevenlabs/service.py` with `SyncResult(outcome: synced|skipped|error)` and `ElevenLabsService.sync_soft_timeout(agent)`.
- [x] 1.3 REFACTOR: make spec the source of truth for payload names (`timeout_secs`, not design draft `timeout_seconds`) and structured log fields (`http_status`, `elevenlabs_agent_id`). Also created `backend/app/elevenlabs/models.py` with `SoftTimeoutConfig` and `SyncResult` Pydantic models.

## Phase 2: Agent Persistence + Schemas (RED → GREEN)

- [x] 2.1 RED: extend `backend/tests/unit/tenants/test_agents.py` to assert the 5 nullable `Agent` columns exist and default to `None`.
- [x] 2.2 GREEN: modify `backend/app/tenants/models.py` with `soft_timeout_seconds`, `soft_timeout_message`, `soft_timeout_use_llm`, `elevenlabs_sync_status`, `elevenlabs_last_synced_at`.
- [x] 2.3 RED: extend `backend/tests/unit/agents/test_schemas.py` for create/update nullable fields, `[0.5, 8.0]` validation, and response sync fields.
- [x] 2.4 GREEN: modify `backend/app/agents/schemas.py` and `_agent_to_response()` in `backend/app/agents/router.py` to expose all 5 new fields. Also updated `create_agent` call in router and `create_agent()` service to accept soft timeout params.
- [x] 2.5 RED/GREEN: add startup compat tests for idempotent agent columns, then modify `backend/app/main.py` with 5 `ALTER TABLE agents ADD COLUMN ... DEFAULT NULL` guards.

## Phase 3: Sync Wiring + Endpoint (RED → GREEN)

- [x] 3.1 RED: create `backend/tests/unit/agents/test_sync_trigger.py` verifying create/update calls `asyncio.create_task` only when EL ID exists and soft-timeout fields are provided/changed.
- [x] 3.2 GREEN: modify `backend/app/agents/router.py` to persist soft-timeout fields, set pending/error/synced via a background helper with its own DB session, and never fail the save.
- [x] 3.3 RED: create `backend/tests/integration/elevenlabs/test_sync_endpoint.py` for `POST .../sync-elevenlabs`: success, skipped without EL ID, 404, and fire-and-forget integration tests.
- [x] 3.4 GREEN: add the awaited re-sync endpoint in `backend/app/agents/router.py`, updating `elevenlabs_sync_status` and `elevenlabs_last_synced_at`.

## Phase 4: Verification

- [x] 4.1 Run `cd backend && python3 -m pytest tests/ -q` — 1822/1822 tests passing (was 1807 before WU2).
- [x] 4.2 EL API field name confirmed: `timeout_secs` (not `timeout_seconds`). PATCH body: `conversation_config.turn.soft_timeout_config` with `enabled`, `timeout_secs`, `message`, `use_llm`. No rate-limit issues observed on test. WebSocket per-conversation override deferred as per spec (OPTIONAL).
