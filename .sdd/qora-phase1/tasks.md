# Tasks: QORA Phase 1 — Multi-client Foundation

## Phase 1: PromptLoader Foundation

- [x] **1.1 [TDD]** Add `tests/unit/prompts/test_loader.py` for `load_prompt`, `load_knowledge`, `render`, sanitization/fallback, using temp client dirs. Depends on none.
- [x] **1.2** Create `backend/app/prompts/loader.py` with `PromptLoader` API, file loading, placeholder rendering, and safe value escaping to satisfy 1.1.
- [x] **1.3** Create `backend/clients/quintana-seguros/prompt.md` and `backend/clients/quintana-seguros/knowledge.md` from the current insurance prompt baseline. Depends on 1.2.
- [x] **1.4** Update `backend/app/prompts/insurance_agent.py` and `backend/app/voice/webhook.py` to route prompt generation through `PromptLoader` while preserving fallback behavior. Depends on 1.2-1.3.

## Phase 2: Knowledge Injection

- [x] **2.1 [TDD]** Extend `tests/unit/prompts/test_loader.py` with scenarios for `knowledge.md` append, no-file behavior, and truncation warning. Depends on 1.1.
- [x] **2.2** Implement knowledge injection in `backend/app/prompts/loader.py`, appending `## INFORMACIÓN DE LA EMPRESA` only when knowledge exists. Depends on 2.1.
- [x] **2.3** Add token estimation + 2000-token truncation in `backend/app/prompts/loader.py`, logging when trimming occurs. Depends on 2.2.

## Phase 3: Client CRUD API

- [x] **3.1 [TDD]** Create `tests/unit/clients/test_router.py` covering POST, GET list, GET item, PATCH, DELETE, plus 422/404/409 cases. Depends on none.
- [x] **3.2** Add `backend/app/clients/__init__.py`, `backend/app/clients/schemas.py`, and `backend/app/clients/router.py` for validated full CRUD and soft delete. Depends on 3.1.
- [x] **3.3** Register `/api/v1/clients` in `backend/app/main.py`. Depends on 3.2.
- [x] **3.4** Keep `/api/v1/tenants` backward compatible by aliasing to the same read paths in `backend/app/tenants/router.py` or shared service wiring. Depends on 3.2.

## Phase 4: CLI and Seed Data

- [x] **4.1** Add Click to `pyproject.toml` and create `backend/qora_cli.py` with `create-client` idempotent scaffolding + DB insert flow. Depends on 3.2.
- [x] **4.2** Remove `default_client_id` and related defaults from `backend/app/core/config.py` and strict-resolution logic in `backend/app/voice/webhook.py` (422 missing, 404 unknown). Depends on 3.3.
- [x] **4.3** Seed `demo-inmobiliaria` plus 3 property leads in `seed.py`, and add `backend/clients/demo-inmobiliaria/prompt.md` + `knowledge.md`. Depends on 4.1-4.2.

## Phase 5: Web Demo Wiring

- [x] **5.1** Update `backend/app/static/index.html` to load active clients into a client `<select>` from `/api/v1/clients`. Depends on 3.3.
- [x] **5.2** Reload the lead dropdown from `/api/v1/leads?client_id={id}` when the client selection changes. Depends on 5.1 and 4.3.
- [x] **5.3** Include selected `client_id` in ElevenLabs `dynamic_variables` on WebSocket/call start. Depends on 5.1.

## Phase 6: Verification

- [x] **6.1** Run the full automated test suite and fix any regressions from PromptLoader, client CRUD, and strict client routing. Depends on 1.4, 2.3, 3.4, 4.3, 5.3.
- [ ] **6.2** Manually verify the web demo can switch between `quintana-seguros` and `demo-inmobiliaria` with distinct leads/prompts. Depends on 5.3.
- [ ] **6.3** Manually verify `/api/v1/voice/custom-llm` returns 404 for unknown `client_id` and 422 when `client_id` is missing. Depends on 4.2.
