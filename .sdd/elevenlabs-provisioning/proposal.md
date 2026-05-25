# Proposal: ElevenLabs Agent Provisioning from Qora Backend

## Intent

ElevenLabs agent configuration (soft timeout, voice behavior) is currently set manually in the ElevenLabs dashboard. When Qora manages multiple agents across tenants, this creates config drift, requires dashboard access per agent, and makes agent settings invisible to the Qora data model. This change gives Qora programmatic control over agent-level ElevenLabs settings — starting with soft timeout, which has a clean API surface and no feasibility unknowns.

## Scope

### In Scope
- New `ElevenLabsService` in `backend/app/elevenlabs/service.py` — async PATCH client with retry and structured error logging
- `Agent` model: 3 new soft-timeout columns (`soft_timeout_seconds`, `soft_timeout_message`, `soft_timeout_use_llm`)
- `Agent` model: 2 new sync-status columns (`elevenlabs_sync_status`, `elevenlabs_last_synced_at`)
- Schema compat in `main.py` — ADD COLUMN IF NOT EXISTS (follows existing pattern, no Alembic)
- `AgentCreate` / `AgentUpdate` / `AgentResponse` Pydantic schema updates
- Auto-sync (fire-and-forget) after agent save in `agents/router.py`
- Manual re-sync endpoint: `POST /api/v1/clients/{client_id}/agents/{agent_id}/sync-elevenlabs`
- Per-conversation soft_timeout_message override via WebSocket init (requires enabling `platform_settings.overrides` on EL agent — one-time dashboard action)

### Out of Scope
- **Tool call sounds** (Phase 2) — Custom LLM tools aren't ElevenLabs-registered tools; feasibility unresolved
- **Agent create/delete** via API — agents remain created manually; Qora only PATCH-updates
- **Alembic migrations** — Qora uses runtime schema compat; this change follows that pattern
- **ElevenLabs tool registration** — deferred until Phase 2 investigation

## Capabilities

### New Capabilities
- `elevenlabs-agent-sync`: Programmatic PATCH of ElevenLabs agent config from Qora; includes service layer, sync-on-save, and manual re-sync endpoint

### Modified Capabilities
- None — no existing spec-level behavior changes (existing TTS override flow is unaffected)

## Approach

1. Create `backend/app/elevenlabs/service.py` with `ElevenLabsService` class: async httpx, retry (3x with backoff), structured logging on failure, returns `SyncResult` (success | skipped | failed).
2. Add soft-timeout and sync-status columns to `Agent` — NULL means "use EL dashboard default", so existing agents are unaffected.
3. Hook `ElevenLabsService.sync_soft_timeout(agent)` into `agents/router.py` after DB commit — fire-and-forget via `asyncio.create_task`. Failures log but do NOT roll back the Qora save.
4. Add `/sync-elevenlabs` re-sync endpoint — idempotent, same service call.
5. Optionally: send `soft_timeout_config.message` in demo-page WebSocket init alongside existing TTS override.

**Key constraint**: Only PATCH `conversation_config.turn.soft_timeout_config`. Never send a full agent body. ElevenLabs preserves unspecified fields — no risk of overwriting dashboard settings.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/elevenlabs/service.py` | New | ElevenLabsService — PATCH soft timeout, retry, logging |
| `backend/app/elevenlabs/__init__.py` | New | Package init |
| `backend/app/tenants/models.py` | Modified | 5 new columns on Agent |
| `backend/app/agents/schemas.py` | Modified | New fields on Create/Update/Response |
| `backend/app/agents/router.py` | Modified | Fire-and-forget sync + re-sync endpoint |
| `backend/app/main.py` | Modified | ADD COLUMN IF NOT EXISTS for 5 new columns |
| `backend/app/static/index.html` | Modified (optional) | soft_timeout_message in WebSocket init |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| EL API unavailable during agent save | Low | Fire-and-forget; save never blocks. Re-sync endpoint for recovery |
| API rate limits on Starter $6/mo plan | Unknown | Log 429s; add debounce if hit in testing |
| EL PATCH overwrites unintended fields | Low | Only send `soft_timeout_config` sub-object; verified PATCH is partial |
| Config drift (EL out of sync with Qora) | Low | `elevenlabs_sync_status` + re-sync endpoint |
| EL API path changes (docs renamed recently) | Low-Med | Pin to `/v1/convai/agents/{id}`; monitor EL changelog |

## Rollback Plan

- New columns are nullable with defaults → existing agents unaffected if feature is unused
- `ElevenLabsService` is isolated; removing the `asyncio.create_task` call in `router.py` fully disables sync
- No schema migration to reverse — `DROP COLUMN` (or just leave nulls) restores prior state
- Re-sync endpoint can be removed without affecting CRUD flow

## Dependencies

- `elevenlabs_api_key` already in `Settings` (`backend/app/core/config.py`) — no new env vars
- `httpx` async client — likely already in `requirements.txt`; confirm before implementing
- ElevenLabs agent must have `platform_settings.overrides.conversation_config_override.turn.soft_timeout_config.message` enabled for per-conversation message override (one-time dashboard action per agent)

## Success Criteria

- [ ] `PATCH /v1/convai/agents/{agent_id}` is called after agent create/update when `soft_timeout_seconds` is set
- [ ] Agent save succeeds even if ElevenLabs PATCH fails (fire-and-forget confirmed)
- [ ] `elevenlabs_sync_status` reflects last sync outcome (success / failed)
- [ ] `/sync-elevenlabs` endpoint re-syncs and returns the updated sync status
- [ ] Agents with all new columns NULL behave identically to today (no regression)
- [ ] Starter plan API key is sufficient — no 402/403 from ElevenLabs PATCH endpoint
