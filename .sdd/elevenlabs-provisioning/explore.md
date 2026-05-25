# Exploration: ElevenLabs Agent Provisioning from Qora Backend

## Current State

### How Qora integrates with ElevenLabs today

Qora uses ElevenLabs Conversational AI as the voice transport layer. The architecture is:

1. **ElevenLabs WebSocket** — connects the end-user's browser to ElevenLabs for audio/TTS/STT.
2. **Custom LLM webhook** — ElevenLabs forwards chat completion requests to Qora's backend (`/api/v1/voice/{client_id}/custom-llm/chat/completions`), where Qora injects tenant context, streams GPT-4o, and handles tool calls.
3. **ElevenLabs agent** — created manually in the ElevenLabs dashboard. Qora only stores the reference `elevenlabs_agent_id` on the `Agent` model.

### What Qora controls today

| Feature | Where configured | Qora's role |
|---------|-----------------|-------------|
| System prompt | Filesystem `system-prompt.md` + DB fallback | Full control (Custom LLM) |
| LLM model/temp/tokens | `Agent` model columns | Full control (Custom LLM) |
| Voice ID | `Agent.voice_id` column | Stored but NOT synced to EL |
| TTS speed/stability/similarity | `Agent.tts_*` columns | Per-conversation override via WebSocket `conversation_config_override.tts` |
| Tool definitions | `Agent.tools_enabled` + `tool_config` columns | Full control (Custom LLM) |
| Tool call sounds | ElevenLabs dashboard only | **No control** |
| Soft timeout | ElevenLabs dashboard only | **No control** |
| First message | ElevenLabs dashboard (with dynamic_variables) | Partial (dynamic_variables from demo) |

### Key code locations

- **`backend/app/tenants/models.py`** — `Agent` model with `elevenlabs_agent_id` (line 61), TTS columns (lines 70-73).
- **`backend/app/agents/schemas.py`** — `AgentCreate`/`AgentUpdate` Pydantic schemas with `elevenlabs_agent_id`, `tts_*` fields.
- **`backend/app/agents/router.py`** — CRUD endpoints. No ElevenLabs API calls; only stores `elevenlabs_agent_id`.
- **`backend/app/voice/webhook.py`** — Custom LLM webhook. Uses `Settings.elevenlabs_api_key` for signed URL generation.
- **`backend/app/voice/context.py`** — `VoiceSessionContext` dataclass with TTS config. `build_voice_context()` factory.
- **`backend/app/core/config.py`** — `Settings` with `elevenlabs_api_key`, `elevenlabs_agent_id`, `elevenlabs_voice_id`.
- **`backend/app/static/index.html`** — Demo page sends `conversation_config_override.tts` and `dynamic_variables` via WebSocket init.

### No dedicated ElevenLabs service module exists

All ElevenLabs API interaction is limited to:
1. `GET /v1/convai/conversation/get_signed_url` — in `webhook.py` signed-url endpoint.
2. No create/update/patch calls to ElevenLabs agents or tools exist anywhere in the codebase.

## ElevenLabs API Surface (from prior research)

### Agent Update — `PATCH /v1/convai/agents/{agent_id}`

Accepts partial updates. Key fields for this change:

```
conversation_config.turn.soft_timeout_config:
  timeout_seconds: int       # seconds of silence before soft timeout fires
  message: str               # what the agent says (filler message)
  use_llm_generated_message: bool  # let LLM generate the message instead
```

**Critical finding**: PATCH only updates fields you send. Fields you omit are preserved. This means we can safely PATCH `soft_timeout_config` without overwriting voice/language/first_message settings.

### Tool Sounds — per-tool via `PATCH /v1/convai/tools/{tool_id}`

Tool call sounds are configured at the **tool level**, not the agent level:

```
tool_config.tool_call_sound: str         # "typing", "elevator1", "elevator2", "elevator3", "elevator4"
tool_config.tool_call_sound_behavior: str  # "always" | "on_long_execution"
```

Endpoints: `POST /v1/convai/tools` (create) and `PATCH /v1/convai/tools/{tool_id}` (update).

**Implication**: To set tool call sounds from Qora, we need to either:
- Know the ElevenLabs tool IDs (stored or queried), OR
- Manage ElevenLabs tool lifecycle from Qora (create tools via API)

### Per-conversation overrides (WebSocket init)

The WebSocket init message supports:
```
conversation_config_override.turn.soft_timeout_config.message: str
```
But ONLY if `platform_settings.overrides.conversation_config_override.turn.soft_timeout_config.message` is enabled on the ElevenLabs agent. The base `timeout_seconds` is NOT overridable per-conversation — only at the agent level.

## Affected Areas

- `backend/app/tenants/models.py` — New columns on Agent model
- `backend/app/agents/schemas.py` — New fields on AgentCreate/AgentUpdate/AgentResponse
- `backend/app/agents/router.py` — Trigger sync after create/update
- `backend/app/core/config.py` — Already has `elevenlabs_api_key` (sufficient)
- **NEW** `backend/app/elevenlabs/service.py` — ElevenLabs API client service
- `backend/app/voice/context.py` — Possible VoiceSessionContext additions
- `backend/app/static/index.html` — Possible soft_timeout override in WebSocket init
- `backend/app/main.py` — Schema compat migration for new columns

## Approaches

### 1. **Dedicated ElevenLabs Service + Async Sync on Save** (Recommended)

Create `backend/app/elevenlabs/service.py` with an `ElevenLabsService` class that wraps the ElevenLabs API. Sync is triggered after successful Agent create/update in the router, but failures do NOT roll back the Qora save.

**Architecture:**
```
Agent Router (create/update)
  └─ Save to DB (commit)
  └─ Fire-and-forget: ElevenLabsService.sync_agent_config(agent)
      ├─ PATCH /v1/convai/agents/{agent_id}  (soft timeout)
      └─ For each tool with sound config:
          └─ PATCH /v1/convai/tools/{tool_id}  (tool call sounds)
```

**New Agent model fields:**
```python
# Soft timeout config
soft_timeout_seconds: int | None          # NULL = use EL dashboard default
soft_timeout_message: str | None          # NULL = use EL dashboard default
soft_timeout_use_llm: bool = False        # let LLM generate the message

# Tool call sound config (per-agent default — applied to all tools)
tool_call_sound: str | None               # "typing", "elevator1-4", NULL = no change
tool_call_sound_behavior: str | None      # "always", "on_long_execution", NULL = no change
```

- Pros: Clean separation. DB save always succeeds. EL sync is best-effort with structured logging. Matches the existing TTS pattern (store on Agent, apply at runtime). No new external dependencies.
- Cons: Potential drift between Qora DB and ElevenLabs state. Need retry/monitoring for failed syncs.
- Effort: Medium

### 2. **Transactional Sync (Sync before DB commit)**

Call ElevenLabs API BEFORE committing the DB transaction. If EL API fails, return 502 to the client.

- Pros: Guaranteed consistency between Qora and ElevenLabs.
- Cons: Agent management becomes fragile — ElevenLabs downtime blocks ALL agent updates. Violates the principle that Qora should be usable even if ElevenLabs is temporarily down. Latency on every save.
- Effort: Medium

### 3. **Separate "Sync to ElevenLabs" action endpoint**

Add `POST /api/v1/clients/{client_id}/agents/{agent_id}/sync-elevenlabs` that explicitly pushes config to ElevenLabs. Agent saves never touch ElevenLabs.

- Pros: User has full control. No coupling between CRUD and ElevenLabs. Can re-sync on demand.
- Cons: Requires manual action. Easy to forget. Config drift by default.
- Effort: Low

### 4. **Hybrid: Sync on save + explicit re-sync endpoint**

Approach 1 + Approach 3 combined. Automatic sync on save (best-effort), plus an explicit re-sync endpoint for recovery.

- Pros: Best of both worlds. Automatic by default, recoverable on failure.
- Cons: Slightly more code. Need to handle idempotency.
- Effort: Medium

## Key Design Decisions

### D1: Per-tool vs per-agent sound config

ElevenLabs models tool call sounds **per-tool** (each ElevenLabs tool has its own `tool_call_sound` field). But Qora's Custom LLM tools are NOT registered as ElevenLabs tools — they're handled entirely by the Custom LLM webhook.

**Problem**: Tool call sounds require ElevenLabs-registered tools. Qora's tools (get_lead_details, capture_data, load_skill) exist only in Qora's backend — ElevenLabs doesn't know about them.

**Options:**
1. **Register Qora tools as ElevenLabs "custom tools"** just to get sound support, even though execution is handled by Custom LLM.
2. **Use a single "proxy tool" in ElevenLabs** with the desired sound, and map all Qora tool calls through it.
3. **Accept that tool call sounds may not be feasible** without a tool registered in ElevenLabs.
4. **Use ambient/filler approach instead** — Qora already has filler speech on tool calls (TOOL_FILLER_PHRASES). This is a voice-level workaround.

**Recommendation**: This needs more investigation. The interaction between Custom LLM tools and ElevenLabs-registered tools with sounds is unclear. Soft timeout is the cleaner, lower-risk feature to implement first.

### D2: Storing ElevenLabs tool IDs

If we go the tool registration route, we need to store ElevenLabs tool IDs in Qora. Options:
- Add a JSON column `elevenlabs_tool_ids` on Agent (map of tool_name → el_tool_id).
- Add a separate table `elevenlabs_tools` with agent_id, tool_name, el_tool_id.

**Recommendation**: Defer until D1 is resolved. If tool sounds aren't feasible via API for Custom LLM setups, this is moot.

### D3: Sync timing

**Recommendation**: Approach 4 (hybrid). Auto-sync on save + explicit re-sync endpoint. This matches the existing pattern where Qora stores config locally and applies it at runtime (TTS override via WebSocket).

### D4: Soft timeout override at conversation level

The demo page already sends `conversation_config_override.tts` via WebSocket init. We could also send `conversation_config_override.turn.soft_timeout_config.message` for per-call customization (e.g., different filler message per lead).

**Prerequisite**: The ElevenLabs agent must have `platform_settings.overrides.conversation_config_override.turn.soft_timeout_config.message` enabled. This is a one-time dashboard setting, OR can be set via the agent PATCH API.

## Recommendation

**Start with soft timeout only (Phase 1), defer tool call sounds (Phase 2).**

**Phase 1 — Soft Timeout:**
1. Add `soft_timeout_seconds`, `soft_timeout_message`, `soft_timeout_use_llm` columns to Agent model.
2. Create `backend/app/elevenlabs/service.py` with `ElevenLabsService.sync_soft_timeout(agent)`.
3. Hook sync into agent create/update router (fire-and-forget, log failures).
4. Add `POST .../sync-elevenlabs` endpoint for manual re-sync.
5. Optionally send `soft_timeout_config.message` override in WebSocket init (demo page + future SDK).

**Phase 2 — Tool Call Sounds (needs investigation):**
1. Determine if Custom LLM tools can have sounds via ElevenLabs tool registration.
2. If yes: design tool registration flow, store EL tool IDs, sync sounds.
3. If no: document limitation, consider workarounds.

## Risks

1. **PATCH field safety** — Low risk. ElevenLabs PATCH preserves unspecified fields (confirmed by API docs). But we should log the full response to detect any unexpected behavior during initial rollout.
2. **API rate limits** — Unknown for Starter plan ($6/mo). Need to test. If rate-limited, sync-on-save could fail for rapid updates. Mitigation: debounce or queue.
3. **Tool call sounds feasibility** — Medium risk. It's unclear whether sounds work with Custom LLM tools that aren't registered in ElevenLabs. This is the biggest unknown.
4. **Config drift** — Low risk with hybrid approach. Auto-sync catches most cases; re-sync endpoint handles edge cases.
5. **No Alembic** — Qora uses runtime schema compat in `main.py` (ADD COLUMN IF NOT EXISTS). New columns follow this pattern, not migrations.
6. **ElevenLabs API breaking changes** — Low-medium risk. ElevenLabs recently moved docs from `conversational-ai` to `eleven-agents` paths. API structure may evolve.

## Ready for Proposal

**Yes** — with the recommendation to scope Phase 1 to soft timeout only. The exploration identified one significant unknown (tool call sounds with Custom LLM) that should be resolved before committing to Phase 2. Soft timeout is clean, well-documented, and low-risk.
