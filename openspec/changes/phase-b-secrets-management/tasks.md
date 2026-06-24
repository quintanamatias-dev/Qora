# Tasks: Phase B8 — Secrets Management

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~600 total; PR #1 ~350, PR #2 ~250 |
| 800-line budget risk | Low |
| 400-line budget risk | High as one PR; Low per slice |
| Chained PRs recommended | Yes |
| Suggested split | PR #1 Core validation → PR #2 Tooling + env/docs cleanup |
| Delivery strategy | auto-forecast |
| Chain strategy | stacked-to-main |
| Decision needed before apply | No |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High
800-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Fail-fast global and active CRM secret validation | PR #1 | Tests first; no env/docs cleanup |
| 2 | Preflight script, root env convention, docs cleanup | PR #2 | Depends on PR #1 credential helpers |

## PR #1: Core Validation (~350 lines)

- [x] 1.1 RED: Add `backend/tests/core/test_config.py` cases for missing/placeholder `OPENAI_API_KEY`, `ELEVENLABS_API_KEY`, and `QORA_API_KEY`.
- [x] 1.2 GREEN: Update `backend/app/core/config.py` model validation to hard-fail required global secrets without logging values.
- [x] 1.3 RED: Add `backend/tests/core/test_credentials.py` for active, disabled, missing, and placeholder CRM credential scenarios.
- [x] 1.4 GREEN: Create `backend/app/core/credentials.py` with placeholder detection and `validate_all_integration_credentials()`.
- [x] 1.5 RED: Add `backend/tests/integrations/test_crm_config_secrets.py` for `enabled: true` default, `enabled: false` skip, env refs, and literal dev values.
- [x] 1.6 GREEN: Update `backend/app/integrations/crm_config.py` with `enabled` and centralized missing/placeholder handling.
- [x] 1.7 RED: Add startup tests proving `backend/app/main.py` calls tenant credential validation and no declared vars use direct `os.getenv()` bypasses.
- [x] 1.8 GREEN: Wire `backend/app/main.py` to settings-backed docs/CORS config and tenant credential validation.
- [x] 1.9 VERIFY: Run focused backend tests for config, credentials, CRM config, and startup behavior.

## PR #2: Tooling + Env/Docs Cleanup (~250 lines)

- [ ] 2.1 RED: Add tests for `backend/scripts/check-secrets.py` success, required missing, placeholder, CRM scan, dead vars, and `--json` output.
- [ ] 2.2 GREEN: Create `backend/scripts/check-secrets.py` with exit 0/1, JSON schema, classification table, and no secret-value output.
- [ ] 2.3 RED: Add tests or assertions for root `.env` loading in `backend/app/main.py`, `backend/scripts/seed_analysis_demo_call.py`, and `backend/scripts/smoke_test_analysis.py`.
- [ ] 2.4 GREEN: Update those three `load_dotenv()` paths to repo-root `.env`; remove/deprecate `backend/.env` path usage.
- [ ] 2.5 GREEN: Move/replace `backend/.env.example` with root `.env.example`; classify active vars and keep `N8N_*`, `TWILIO_*`, `BROKER_NAME` only if truly future/dead.
- [ ] 2.6 GREEN: Update `frontend/.env.example` with the browser-visible `VITE_API_KEY` warning and Phase C JWT replacement note.
- [ ] 2.7 GREEN: Create `docs/ops/secrets-management.md` and update practical docs that still point to `backend/.env`; coordinate with existing uncommitted B5-B7 docs updates.
- [ ] 2.8 HYGIENE: Do not touch `.atl/.skill-registry.cache.json` or `.atl/skill-registry.md`; verify protected files are unchanged before PR prep.
- [ ] 2.9 VERIFY: Run focused script tests, env convention checks, docs link checks, and relevant backend suite.
