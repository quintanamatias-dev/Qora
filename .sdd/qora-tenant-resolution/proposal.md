# Proposal: Tenant Resolution via URL Path

**Change**: qora-tenant-resolution  
**Date**: 2026-04-18  
**Status**: Draft

---

## Intent

The multi-tenant custom-LLM webhook currently resolves `client_id` from the request body (`elevenlabs_extra_body.client_id` or top-level). ElevenLabs' dashboard (April 2026) does not expose a reliable UI toggle to populate this field — all incoming requests arrive with `client_id: null`, causing HTTP 422 responses, WebSocket closure with `custom_llm_error`, and a completely broken call experience. Moving the tenant identifier into the URL path (`/voice/{client_id}/custom-llm/chat/completions`) eliminates this dependency entirely: the URL is the only data channel ElevenLabs cannot strip or null out.

---

## Scope

### In Scope

- New route: `POST /api/v1/voice/{client_id}/custom-llm/chat/completions`
- Keep legacy route `POST /api/v1/voice/custom-llm/chat/completions` with deprecation warning (still returns 422 if no `client_id` in body — behavior unchanged)
- Update `backend/app/voice/webhook.py` to extract `client_id` from path param
- New unit tests: path-based resolution happy path + 404 for unknown `client_id`
- Update integration tests to use the new path
- New `docs/elevenlabs-setup.md`: correct dashboard URL configuration instructions

### Out of Scope

- Removing the legacy route (deferred to next change)
- Changing the initiation webhook URL shape (already works via query param)
- Per-agent routing at the `agent_id` level (future work)
- Frontend changes — `index.html` does NOT call custom-LLM directly; no touch needed
- Auth/signing of the tenant path (future hardening)

---

## Capabilities

### New Capabilities

- `path-based-tenant-resolution`: custom-LLM webhook resolves `client_id` from URL path parameter, bypassing ElevenLabs body forwarding entirely

### Modified Capabilities

- `client-routing` (existing `CAP-6` from qora-phase1): extend resolution priority — URL path param is the **primary** source; body fields (`elevenlabs_extra_body`, top-level) are **legacy fallback** for deprecated route only

---

## Approach

Add a new FastAPI path-param route alongside the existing one. The new handler extracts `client_id` directly from the URL, validates it against the DB (existing `get_client()` call), and proceeds with the normal webhook flow. The legacy route remains untouched except for a deprecation log warning. ElevenLabs dashboard must be updated once per agent to point to the new URL.

```python
# New route — client_id guaranteed by routing
@router.post("/{client_id}/custom-llm/chat/completions")
async def custom_llm_webhook(client_id: str, body: CustomLLMRequest, request: Request):
    client = await get_client(client_id)  # raises 404 if not found
    ...

# Legacy route — kept with deprecation warning
@router.post("/custom-llm/chat/completions")
async def custom_llm_webhook_legacy(body: CustomLLMRequest, request: Request):
    logger.warning("DEPRECATED: Use /voice/{client_id}/custom-llm/chat/completions")
    client_id = extra.client_id or body.client_id or ...  # existing logic, still 422 if null
    ...
```

ElevenLabs appends `/chat/completions` to whatever base URL is configured in the dashboard. The user sets the base URL to `.../api/v1/voice/quintana-seguros/custom-llm` → EL constructs `.../api/v1/voice/quintana-seguros/custom-llm/chat/completions`.

---

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/voice/webhook.py` | Modified | Add new path-param route; add deprecation warning to legacy route |
| `backend/app/voice/router.py` | Modified | Register new route alongside existing one |
| `backend/tests/unit/voice/` | New tests | Happy path for path-based resolution; 404 for unknown `client_id` |
| `backend/tests/integration/` | Modified | Update EL integration tests to use new path |
| `docs/elevenlabs-setup.md` | New | Dashboard config instructions with correct URL format |
| `backend/app/static/index.html` | No change | Frontend never calls custom-LLM directly |

---

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| EL mangles URL when it appends `/chat/completions` to a path with segments | Low | Verify with a real curl test before declaring done; EL docs confirm suffix appending behavior |
| Dashboard misconfiguration (user sets full URL including `/chat/completions`) | Med | `docs/elevenlabs-setup.md` explicitly shows what to enter and what NOT to enter |
| Legacy route silently broken by route ordering in FastAPI | Low | Register path-param route before legacy route; add route-ordering test |

---

## Rollback Plan

- Legacy route is untouched and still functional — revert EL dashboard URL to the old endpoint in under 2 minutes
- If the new route is removed from code, EL agent reverts to legacy behavior immediately
- No DB migrations — purely an HTTP routing change

---

## Dependencies

- qora-phase1 complete (multi-tenant foundation, `client_id` validation in place) ✅
- ElevenLabs agent already configured with a Custom LLM URL (requires one-time dashboard update)

---

## Success Criteria

- [ ] `POST /api/v1/voice/quintana-seguros/custom-llm/chat/completions` returns 200 with a valid streaming response
- [ ] `POST /api/v1/voice/ghost-client/custom-llm/chat/completions` returns HTTP 404
- [ ] Legacy route `POST /api/v1/voice/custom-llm/chat/completions` still works (returns 422 if no `client_id` in body — no regression)
- [ ] ElevenLabs call completes end-to-end without `custom_llm_error` after dashboard URL update
- [ ] `docs/elevenlabs-setup.md` exists and accurately describes dashboard configuration
- [ ] All existing tests pass
