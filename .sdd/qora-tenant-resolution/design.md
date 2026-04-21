# Design: Path-Based Tenant Resolution

## Technical Approach

Add a path-param route `/{client_id}/custom-llm/chat/completions` to `webhook.py`. Extract core webhook logic into a shared helper `_process_custom_llm_request()` that both the new route and the legacy route call. Legacy route stays functional with deprecation logging. No DB migrations, no frontend changes.

## Architecture Decisions

| Decision | Choice | Alternatives | Rationale |
|----------|--------|-------------|-----------|
| Route ordering | Register LEGACY first, then path-param | Path-param first; single route with optional param | FastAPI matches routes in registration order. Literal `/custom-llm/...` must match before `/{client_id}/...` to prevent `custom-llm` being captured as a `client_id` value. |
| Inactive tenant response | HTTP 403 `"Tenant disabled"` | 404 (hide existence) | 403 is more informative for debugging EL misconfig. Tenant existence is not security-sensitive (slug-based IDs are public in the URL). |
| `conversation_id` source | Top-level body field > `elevenlabs_extra_body` > `None` | Only extra_body; only top-level | Matches existing resolution pattern. If both exist and differ, log `conversation_id_mismatch` warning, prefer top-level. |
| Client ID mismatch (path vs body) | Use path value, log warning, continue | Reject request (400) | Path is authoritative (EL dashboard config). Body mismatch is EL misconfiguration, not a security threat. Rejecting would break calls unnecessarily. |
| Code dedup strategy | Private `_process_custom_llm_request()` helper | Shared via class/mixin; decorator | Project uses plain functions with `structlog`. A helper function is the simplest pattern that satisfies CAP-3. |

## Data Flow

```
Frontend ──WS──> ElevenLabs ──POST──> QORA Backend
                     │
          ┌──────────┴───────────┐
          v                      v
  POST /voice/initiation   POST /voice/{client_id}/custom-llm/chat/completions
  ?client_id=X              (NEW: client_id from URL path)
  [200 OK]                       │
                                 v
                         _process_custom_llm_request(body, client_id, request)
                                 │
                    ┌────────────┼────────────┐
                    v            v            v
               get_client()  PromptLoader  OpenAIStreamingClient
                    │                         │
                    v                         v
               CallSession              SSE stream → EL → user
```

Legacy route (`/voice/custom-llm/chat/completions`) feeds the same `_process_custom_llm_request()` after resolving `client_id` from body fields.

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/app/voice/webhook.py` | Modify | Extract `_process_custom_llm_request()` helper. Add `custom_llm_webhook_path()` handler. Rename existing handler to `custom_llm_webhook_legacy()`, add deprecation log. Reorder route decorators: legacy FIRST, path-param SECOND. |
| `backend/tests/integration/voice/test_custom_llm.py` | Modify | Add path-based route tests (happy, 404, 403, mismatch). Add deprecation log assertion for legacy route tests. |
| `backend/tests/unit/voice/test_custom_llm_path_route.py` | Create | Focused unit tests for path-based resolution, mismatch handling, inactive tenant 403. |
| `docs/elevenlabs-setup.md` | Create | Dashboard config instructions: base URL format, common gotchas. |

## Interfaces / Contracts

```python
# New path-param handler — registered SECOND
@router.post("/{client_id}/custom-llm/chat/completions")
async def custom_llm_webhook_path(client_id: str, body: CustomLLMRequest, request: Request):
    # Mismatch detection
    body_client_id = body.elevenlabs_extra_body.client_id or body.client_id
    if body_client_id and body_client_id != client_id:
        logger.warning("client_id_mismatch", path_client_id=client_id, body_client_id=body_client_id)
    logger.info("custom_llm_path_request", client_id=client_id, ...)
    return await _process_custom_llm_request(body=body, client_id=client_id, request=request)

# Legacy handler — registered FIRST (literal path wins over param)
@router.post("/custom-llm")
@router.post("/custom-llm/chat/completions")
@router.post("/chat/completions")
async def custom_llm_webhook_legacy(body: CustomLLMRequest, request: Request):
    client_id = extra.client_id or body.client_id or ...  # existing logic
    if not client_id: raise HTTPException(422, ...)
    logger.warning("custom_llm_legacy_route_used", client_id=client_id,
                    hint="/api/v1/voice/{client_id}/custom-llm/chat/completions")
    return await _process_custom_llm_request(body=body, client_id=client_id, request=request)

# Shared helper — ALL business logic lives here
async def _process_custom_llm_request(*, body: CustomLLMRequest, client_id: str, request: Request):
    # 1. Tenant lookup: get_client() → 404 if None, 403 if inactive
    # 2. Resolve conversation_id (top-level > extra_body > generate)
    # 3. Load lead, build prompt, stream LLM — identical to current logic
    ...
```

Tenant validation inside `_process_custom_llm_request`:
```python
async with db_session() as db:
    client = await get_client(db, client_id)
    if client is None:
        raise HTTPException(404, detail={"error": "client not found"})
    if not client.is_active:
        logger.warning("tenant_lookup_failed", client_id=client_id, reason="inactive")
        raise HTTPException(403, detail={"error": "Tenant disabled"})
```

## Structured Logging Events

| Event | Level | Fields | Emitted by |
|-------|-------|--------|------------|
| `custom_llm_path_request` | info | `client_id`, `conversation_id`, `message_count`, `model` | Path handler |
| `custom_llm_legacy_route_used` | warning | `client_id`, `conversation_id`, `source`, `migration_hint` | Legacy handler |
| `client_id_mismatch` | warning | `path_client_id`, `body_client_id` | Path handler |
| `tenant_lookup_failed` | warning | `client_id`, `reason` (`not_found` or `inactive`) | Shared helper |
| `conversation_id_mismatch` | warning | `top_level`, `extra_body` | Shared helper |

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | Path route: happy/404/403/mismatch (8 scenarios) | `test_custom_llm_path_route.py` — FastAPI TestClient, isolated SQLite, respx for OpenAI |
| Integration | Legacy route: deprecation log, body-resolution, 422/404 (7 scenarios) | Extend `test_custom_llm.py` — add log assertions via structlog capture |
| Integration | Both routes produce identical SSE for same tenant+body (CAP-3) | Same test file — parametrize over both URLs |
| Unit | Concurrent different-tenant requests — no cross-contamination | Async gather of two requests, assert independent sessions |

Covers all 18 spec scenarios across CAP-1 (7), CAP-2 (7), CAP-3 (3), plus the implicit routing scenario.

## Migration / Rollout

No DB migration. Pure additive HTTP routing change.

1. Deploy code with both routes active
2. Update EL dashboard: set Custom LLM base URL to `.../api/v1/voice/{client_id}/custom-llm`
3. EL appends `/chat/completions` automatically
4. Legacy route remains functional indefinitely — removal deferred to `qora-tenant-resolution-cleanup`

Rollback: revert EL dashboard URL to old endpoint (< 2 min).

## Open Questions

- [x] Route ordering — **resolved**: legacy first, path-param second
- [x] Inactive tenant response — **resolved**: 403
- [x] `conversation_id` source — **resolved**: top-level > extra_body > generate
- [ ] Verify EL correctly appends `/chat/completions` to a multi-segment base URL (one manual curl test before declaring done)
