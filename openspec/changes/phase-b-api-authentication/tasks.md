# Tasks: Phase B5 — API Authentication

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~1,100 total; PR #1 ~500, PR #2 ~400, PR #3 ~200 |
| 800-line budget risk | Medium overall; Low per PR slice |
| 400-line budget risk | High overall; Medium/Low per slice |
| Chained PRs recommended | Yes — user approved exactly 3 PR slices |
| Suggested split | PR #1 Foundation + Admin Auth → PR #2 Session Auth + Demo + Tool Scope → PR #3 Webhook Auth + CORS |
| Delivery strategy | auto-forecast |
| Chain strategy | pending — user must choose stacked-to-main or feature-branch-chain before apply/PR creation |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High
800-line budget risk: Medium

## PR #1 — Foundation + Admin Auth (~500 lines)

- [x] 1.1 RED: Add auth/config tests in `backend/tests/test_auth.py`, router 401 tests, and `frontend/src/api/client.ts` header test if supported.
- [x] 1.2 GREEN: Add `QORA_API_KEY`, docs toggle, demo IDs, and TTL settings in `backend/app/core/config.py`; create `backend/app/core/auth.py` with `CallerIdentity` and `require_api_key()`.
- [x] 1.3 GREEN: Protect admin routers in `backend/app/{clients,agents,leads,calls,analytics,scheduler}/router.py` and `backend/app/integrations/*router.py`; keep `/api/v1/health`, `/docs`, `/redoc`, and `/demo` public.
- [x] 1.4 GREEN: Update `backend/tests/conftest.py`, `frontend/src/api/client.ts`, `backend/.env.example`, and `frontend/.env.example` for bearer auth.
- [x] 1.5 VERIFY: Run backend auth/router tests and frontend API-client tests; confirm no `.atl/*` files or unrelated `docs/ROADMAP.md` changes are touched.

## PR #2 — Session Auth + Demo + Tool Scope (~400 lines)

- [x] 2.1 RED: Add tests for `AuthorizedSession` creation, session-store lookup, demo context/leads safety, full demo pipeline writes, tool scope denial, and zero per-turn DB/network auth lookup.
- [x] 2.2 GREEN: Add `AuthorizedSession` to `backend/app/core/auth.py` and `ConversationState.auth` in `backend/app/voice/session.py`; bind auth once at session start in `backend/app/voice/initiation.py`.
- [x] 2.3 GREEN: Create `backend/app/demo/router.py` with public `/api/v1/demo/context` and `/api/v1/demo/leads`; preserve `/demo` as public/easy and never expose admin keys.
- [x] 2.4 GREEN: Update `backend/app/static/index.html` for demo button flow: load context, load demo leads, user starts conversation; do not route demo through scheduled calls.
- [x] 2.5 GREEN: Pass cached `AuthorizedSession` through `backend/app/voice/webhook.py` into `backend/app/tools/dispatcher.py`; tools are backend actions requested by the agent and must check cached session scope before data access.
- [x] 2.6 VERIFY: Prove custom-LLM turns use cached auth with zero DB/network auth lookup; verify scheduler flow remains future-designed only, with no implication demo uses scheduled calls.

## PR #3 — Webhook Auth + CORS (~200 lines)

- [x] 3.1 RED: Add webhook secret enabled/disabled tests and CORS origin tests in backend auth/main tests.
- [x] 3.2 GREEN: Add disabled-by-default `require_webhook_secret()` to `backend/app/core/auth.py` and wire voice webhook endpoints without breaking existing ElevenLabs agents.
- [x] 3.3 GREEN: Replace wildcard CORS in `backend/app/main.py` with `QORA_ALLOWED_ORIGINS`; document rollout vars in `backend/.env.example`.
- [x] 3.4 VERIFY: If webhook auth is enabled, manually configure ElevenLabs secret, run a live demo call, confirm transcript writes; remove secret to confirm 401, then restore.
- [x] 3.5 VERIFY: Confirm allowed origins work, rejected origins fail, webhook auth remains off by default, and file hygiene constraints still hold.
