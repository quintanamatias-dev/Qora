# Remove the Qora demo agent

Goal: delete the `qora-demo` client, its `qora-explainer` agent ("Mariano"), the public `/demo` page, its seeding and everything that only exists for it, with no leftovers in code, the database or ElevenLabs. The user asked for this as a task separate from config phase 1.

Branch `chore/remove-qora-demo`, stacked on `feat/config-phase1b`. Not pushed. Production steps (data migration at deploy, ElevenLabs agent deletion, Railway variable) wait for the user's go-ahead.

## Tasks

- [x] 1. Admin "test call in browser" (`GET /voice/signed-url`): nothing calls it (no frontend caller; only a tenant-isolation test), and it is bound to the global demo `ELEVENLABS_AGENT_ID`. Decision: delete it in task 2 instead of making it per-agent; a per-agent browser test call can be built later if needed.
- [x] 2. Remove demo code: `seed_qora_demo` and its constants, `app/demo/` router, `app/static/index.html` page and its `/demo` mount, `qora_demo_*` settings, the global `elevenlabs_agent_id` / `elevenlabs_voice_id` defaults, `backend/clients/qora-demo/`. Delete demo-only tests; re-point tests that only used qora-demo as a fixture.
- [x] 3. Update docs and skills (`skills/qora-agent-designer` needs a new canonical example: Quintana `leads-agent`). Historical audit and openspec records stay as they are.
- [ ] 4. One-off Alembic data migration that hard-deletes every `qora-demo` row in FK-safe order (no cascades exist; the API only soft-deletes).
- [ ] 5. Full backend and frontend suites green; production steps written down.

## Production steps (wait for the user)

- Deploy (the migration deletes the qora-demo data).
- Delete ElevenLabs agent `agent_4701m3ynzr4jfb0tyj836t437rbh` (Qora Demo - qora-explainer (prod)).
- Remove `ELEVENLABS_AGENT_ID` (and any `QORA_DEMO_*`) from Railway.

## Evidence

- Exploration (path:line map) delivered by gentle-ai-explore; prod qora-demo has 1 agent and 0 calls.
- Task 2: the worker removed the seed, router, mount, settings and signed-url, and re-pointed ~20 test files (new `tests/helpers/second_tenant.py`; pipeline tests now use Quintana leads-agent). The parent ran the `git rm` of app/demo, app/static, clients/qora-demo and 3 demo-only test files (the worker cannot delete), cleaned `.env.example`, and renamed 2 doc-string examples. Settings use `extra: ignore`, so a leftover Railway `ELEVENLABS_AGENT_ID` is harmless. Verifier: backend 3857 passed, frontend 891 passed, lint and tsc clean, app imports; ruff has 2 pre-existing findings in main.py.
