# Design: ElevenLabs Agent Provisioning — Phase 1 (Soft Timeout)

## Technical Approach

New `backend/app/elevenlabs/` package with a single `ElevenLabsService` class that PATCHes the ElevenLabs ConvAI agent API. The service is injected via FastAPI `Depends()`, triggered fire-and-forget after agent DB commit, and exposes a manual re-sync endpoint. Follows Qora's existing patterns: flat nullable columns, runtime schema compat, `asyncio.create_task` for background work (same as `schedule_user_turn_persist`).

## Architecture Decisions

| Decision | Choice | Alternatives | Rationale |
|----------|--------|-------------|-----------|
| Service location | `backend/app/elevenlabs/service.py` | Inside `agents/` or `voice/` | Dedicated package mirrors future Phase 2 growth; keeps agent CRUD and voice webhook clean |
| httpx client lifecycle | Per-call `async with httpx.AsyncClient()` | Shared/singleton client | Matches `webhook.py:get_signed_url` pattern (L94); sync calls are infrequent (agent save only); no connection pool benefit |
| DI pattern | `Depends()` factory returning `ElevenLabsService` | Direct instantiation | Enables test injection; service needs `Settings.elevenlabs_api_key` which is already on `app.state.settings` |
| Background task DB session | Own session via `get_session()` context manager | Reuse request session | Request session closes after response; background task needs independent session lifecycle (same pattern as `db_session()` in webhook.py L389) |
| Retry strategy | 1 retry on 5xx/timeout, 1s backoff | 3 retries (proposal), exponential | Phase 1 simplicity; re-sync endpoint covers persistent failures; avoids blocking create_task for 10s+ |
| Sync trigger | After both create AND update, only when `elevenlabs_agent_id` is set and soft-timeout fields changed | Always sync | Skip sync when no EL agent bound (new agents without EL ID); skip when soft-timeout fields unchanged |

## Data Flow

```
Agent Create/Update (router.py)
    │
    ├─ DB commit + refresh  (request session)
    │
    ├─ Response returned to client  ← sync_status may still be "pending"
    │
    └─ asyncio.create_task(sync_to_elevenlabs(agent_id, client_id))
            │
            ├─ async with get_session() as db:   ← NEW independent session
            │     └─ SELECT agent by id
            │
            ├─ ElevenLabsService.sync_soft_timeout(agent)
            │     └─ PATCH https://api.elevenlabs.io/v1/convai/agents/{el_agent_id}
            │          body: { conversation_config: { turn: { soft_timeout_config: {...} } } }
            │
            └─ UPDATE agent SET elevenlabs_sync_status, elevenlabs_last_synced_at
                  └─ db.commit()
```

Re-sync endpoint: `POST .../sync-elevenlabs` → same `ElevenLabsService.sync_soft_timeout()` but awaited (not fire-and-forget), returns updated `AgentResponse`.

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/app/elevenlabs/__init__.py` | Create | Package init (empty) |
| `backend/app/elevenlabs/service.py` | Create | `ElevenLabsService` class + `sync_to_elevenlabs` background helper |
| `backend/app/tenants/models.py` | Modify | 5 new nullable columns on Agent: `soft_timeout_seconds`, `soft_timeout_message`, `soft_timeout_use_llm`, `elevenlabs_sync_status`, `elevenlabs_last_synced_at` |
| `backend/app/agents/schemas.py` | Modify | Add fields to `AgentCreate`, `AgentUpdate`, `AgentResponse` |
| `backend/app/agents/router.py` | Modify | Import sync helper, add `create_task` after create/update commit, add `/sync-elevenlabs` endpoint, update `_agent_to_response` |
| `backend/app/main.py` | Modify | 5 new `ADD COLUMN IF NOT EXISTS` in `_ensure_startup_schema_compat` |
| `backend/tests/unit/elevenlabs/test_service.py` | Create | Unit tests for `ElevenLabsService` with respx |
| `backend/tests/unit/agents/test_sync_trigger.py` | Create | Integration test: agent save triggers sync task |

## Interfaces / Contracts

```python
# backend/app/elevenlabs/service.py

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

class SyncStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"  # no elevenlabs_agent_id or no soft-timeout fields set

@dataclass
class SyncResult:
    status: SyncStatus
    error: str | None = None
    synced_at: datetime | None = None

class ElevenLabsService:
    def __init__(self, api_key: str):
        self._api_key = api_key

    async def sync_soft_timeout(
        self,
        elevenlabs_agent_id: str,
        soft_timeout_seconds: int,
        soft_timeout_message: str | None = None,
        soft_timeout_use_llm: bool = False,
    ) -> SyncResult:
        """PATCH soft_timeout_config on ElevenLabs agent. 1 retry on 5xx."""
        ...

# Background helper (module-level, called via create_task)
async def sync_to_elevenlabs(agent_id: str) -> None:
    """Load agent from DB, call service, update sync status."""
    ...

# FastAPI dependency
async def get_elevenlabs_service(request: Request) -> ElevenLabsService:
    api_key = request.app.state.settings.elevenlabs_api_key.get_secret_value()
    return ElevenLabsService(api_key=api_key)
```

```python
# ElevenLabs PATCH payload shape
{
    "conversation_config": {
        "turn": {
            "soft_timeout_config": {
                "timeout_seconds": 30,           # soft_timeout_seconds
                "message": "Are you still there?", # soft_timeout_message (optional)
                "use_llm": false                   # soft_timeout_use_llm
            }
        }
    }
}
```

```python
# New Agent model columns (models.py)
soft_timeout_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
soft_timeout_message: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
soft_timeout_use_llm: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
elevenlabs_sync_status: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
elevenlabs_last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `ElevenLabsService.sync_soft_timeout` — success, 4xx error, 5xx retry, timeout | respx mock (already in pyproject.toml deps); test `SyncResult` values |
| Unit | `sync_to_elevenlabs` background helper — skips when no EL agent ID, updates sync_status | Mock `ElevenLabsService`, use real in-memory SQLite |
| Unit | Schema validation — nullable fields, defaults, response shape | Extend `test_schemas.py` |
| Integration | Agent create/update → verify `create_task` was called with correct args | `unittest.mock.patch("asyncio.create_task")` in existing `test_router.py` pattern |
| Integration | Re-sync endpoint returns updated sync_status | httpx `AsyncClient` against test app (existing fixture pattern) |

## Migration / Rollout

No data migration. Runtime schema compat via `_ensure_startup_schema_compat` in `main.py`:
- 5 `ADD COLUMN IF NOT EXISTS` statements (SQLite `ALTER TABLE`)
- All columns nullable with `DEFAULT NULL` — existing agents unaffected
- `elevenlabs_sync_status` starts as NULL (meaning "never synced"), not "pending"

## Open Questions

- [ ] ElevenLabs PATCH field name: is it `timeout_seconds` or `timeout`? Verify against actual API response before implementation
- [ ] Does the Starter plan ($6/mo) have rate limits on the PATCH endpoint? Test empirically during implementation
