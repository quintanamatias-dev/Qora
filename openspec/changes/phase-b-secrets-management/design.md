# Design: Phase B8 — Secrets Management

## Technical Approach

Centralize all secret loading through `Settings`, add tier-based startup validation, create a credential resolver for per-client integrations, and ship a pre-flight script. Zero new dependencies; extends existing pydantic-settings patterns already proven in B5.

**`.env` convention**: Repo-root `.env` is the single source of truth for all environments (local dev, Docker, CI). `backend/.env` is deprecated and will be deleted. All `load_dotenv()` calls and pydantic-settings `env_file` paths are updated to resolve to the repo root.

Maps to proposal approach items 1–7 and covers all four specs: `secrets-validation`, `secrets-preflight`, `tenant-integration-secrets`, `env-file-conventions`.

## Architecture Decisions

### Decision: Startup Validation Location

| Option | Tradeoff | Decision |
|--------|----------|----------|
| `@model_validator` on Settings | Fires at construction; can't scan crm.yaml files (no client context) | **Use for CRITICAL/HIGH global secrets** |
| Lifespan startup hook (post-Settings) | Has access to filesystem for crm.yaml scanning | **Use for tenant integration secrets** |
| Separate CLI-only check | Doesn't protect runtime | Rejected — validation must be runtime too |

**Rationale**: Two-phase validation mirrors the existing pattern: `Settings.__init__` validates platform secrets (like the existing `validate_webhook_secret_when_enabled`), then a lifespan hook validates tenant integration secrets that require filesystem access.

### Decision: Credential Resolver Scope

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Extend `CRMConfig.resolve_api_key()` | Already exists; already does env var vs literal heuristic | **Keep existing method as-is** |
| New `backend/app/core/credentials.py` | Centralized; future HubSpot extends here | **Add thin wrapper for startup validation loop** |
| Move all credential logic into Settings | Couples Settings to client filesystem | Rejected |

**Rationale**: `CRMConfig.resolve_api_key()` already implements the ALL_CAPS heuristic correctly. The new `credentials.py` module provides a `validate_all_integration_credentials()` function that iterates client crm.yaml files, calls `resolve_api_key()`, and collects errors. The resolver stays in `crm_config.py`; the validator loop lives in `credentials.py`. HubSpot/future integrations extend the same pattern.

### Decision: `.env` Source of Truth

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Root `.env` only — update all paths | Clean; no duplication; one file for Docker + local dev + scripts | **Chosen** |
| Root `.env` + symlink `backend/.env → ../.env` | Avoids code changes but adds fragile indirection | Rejected — unnecessary complexity |
| Keep both copies, document sync | Divergence risk (already diverged: root dated Jun 20, backend dated May 29) | Rejected |

**Rationale**: Code inspection shows exactly 3 `load_dotenv()` calls that hardcode `backend/.env`:
1. `backend/app/main.py` line 45: `load_dotenv(Path(__file__).resolve().parent.parent / ".env")`
2. `backend/scripts/seed_analysis_demo_call.py` line 32: `load_dotenv(BACKEND_DIR / ".env")`
3. `backend/scripts/smoke_test_analysis.py` line 32: `load_dotenv(Path(__file__).resolve().parent.parent / ".env")`

All three can be updated to resolve `../../.env` (two parents up from `backend/`) or use a shared helper. pydantic-settings `env_file: ".env"` in `config.py` is CWD-relative — Docker already runs from repo root; local dev typically runs from `backend/`, but `load_dotenv()` fires first and populates `os.environ`, so pydantic-settings reads from env vars directly (its `env_file` is a fallback). No symlink needed.

`backend/.env` is deleted after the migration. `.gitignore` already covers `*.env` at both levels.

### Decision: `.env.example` Location

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Move `backend/.env.example` → root `.env.example` | Matches the single root `.env` convention; one obvious place | **Chosen** |
| Keep `backend/.env.example`, update header only | Confusing: example in `backend/` but actual file at root | Rejected |
| Both root and backend examples | Same duplication problem we're fixing | Rejected |

**Rationale**: Since `.env` lives at root, `.env.example` should live at root too. The header instructions simplify to: "Copy to `.env` and fill in values." `frontend/.env.example` stays where it is (different concern).

### Decision: crm.yaml Enabled/Disabled Convention

| Option | Tradeoff | Decision |
|--------|----------|----------|
| `enabled: true/false` field in crm.yaml | Explicit; requires field addition | **Adopt** — presence of file + `enabled: true` (default) |
| File presence = enabled | No way to disable without deleting | Rejected |
| Separate `integrations.yaml` | New file format | Rejected — overengineered |

**Rationale**: Default `enabled: true` preserves backward compat (existing crm.yaml files work unchanged). Setting `enabled: false` skips credential validation and runtime use. Matches user decision: "active/configured integrations with missing credentials must fail clearly."

### Decision: `check-secrets.py` Location

| Option | Tradeoff | Decision |
|--------|----------|----------|
| `backend/scripts/check-secrets.py` | Consistent with existing `backend/scripts/migrate.py` | **Chosen** |
| Root `scripts/check-secrets.py` | No `scripts/` dir at root | Rejected |

## Data Flow

```
Startup:
┌─────────────────────────────────┐
│ main.py: load_dotenv(root/.env) │ ← populates os.environ from ROOT
│ Settings()                      │ ← @model_validator validates
│   ├─ CRITICAL: OPENAI_API_KEY   │   CRITICAL/HIGH global secrets
│   ├─ CRITICAL: ELEVENLABS_*     │   + placeholder rejection
│   ├─ HIGH: QORA_API_KEY         │
│   └─ CONDITIONAL: WEBHOOK_*     │   (existing B5 validator)
└──────────────┬──────────────────┘
               ▼
┌─────────────────────────────────┐
│ lifespan(): validate_tenant_    │ ← post-Settings, pre-request
│   integration_credentials()     │
│   ├─ scan backend/clients/*/    │
│   │   crm.yaml                  │
│   ├─ skip if no crm.yaml or    │
│   │   enabled: false            │
│   └─ resolve_api_key() per      │   Hard fail if missing/placeholder
│      active integration         │
└──────────────┬──────────────────┘
               ▼
         App serves requests
```

```
Pre-deploy:
┌─────────────────────────────────┐
│ check-secrets.py                │
│   ├─ load .env (root)           │
│   ├─ check REQUIRED vars        │
│   ├─ check placeholder values   │
│   ├─ scan crm.yaml → env refs   │
│   ├─ detect dead vars           │
│   └─ print table / --json       │
│       exit 0 (ok) / 1 (fail)    │
└─────────────────────────────────┘
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/app/core/config.py` | Modify | Add `@model_validator` for CRITICAL/HIGH secrets + placeholder rejection |
| `backend/app/core/credentials.py` | Create | `validate_all_integration_credentials(clients_root)` — startup hook; `WEAK_PLACEHOLDERS` list |
| `backend/app/main.py` | Modify | Update `load_dotenv()` path to repo root; replace 2 `os.getenv()` calls with `settings.*`; call `validate_all_integration_credentials()` in lifespan |
| `backend/app/integrations/crm_config.py` | Modify | Add `enabled: bool = True` field to `CRMConfig`; add placeholder check to `resolve_api_key()` |
| `backend/scripts/check-secrets.py` | Create | Pre-flight validation script with `--json` flag |
| `backend/scripts/seed_analysis_demo_call.py` | Modify | Update `load_dotenv()` path to repo root |
| `backend/scripts/smoke_test_analysis.py` | Modify | Update `load_dotenv()` path to repo root |
| `.env.example` | Create | Moved from `backend/.env.example` — full reclassification: REQUIRED/OPTIONAL/PER_CLIENT/FUTURE sections |
| `backend/.env.example` | Delete | Replaced by root `.env.example` |
| `backend/.env` | Delete | Deprecated — root `.env` is the single source of truth |
| `frontend/.env.example` | Modify | Add VITE_API_KEY browser-visibility warning |
| `docs/ops/secrets-management.md` | Create | Operator runbook |

## Interfaces / Contracts

```python
# backend/app/core/credentials.py

WEAK_PLACEHOLDERS: set[str] = {
    "change-me-before-production",
    "your-key-here",
    "TODO",
    "REPLACE_ME",
    "xxx",
    "test",
    "changeme",
}

def is_weak_placeholder(value: str) -> bool:
    """Check if value matches a known weak placeholder (case-insensitive)."""
    ...

def validate_all_integration_credentials(
    clients_root: Path | None = None,
) -> None:
    """Scan all crm.yaml files; hard-fail if any active integration
    references an env var that is missing or is a weak placeholder.
    
    Raises:
        SystemExit: with clear error naming client + missing var.
    
    Logging: logs client_id and var name; NEVER logs the secret value.
    """
    ...

# backend/app/integrations/crm_config.py — CRMConfig additions
class CRMConfig(BaseModel):
    enabled: bool = True  # NEW — default True for backward compat
    ...
```

```python
# backend/app/main.py — load_dotenv path change
# BEFORE: load_dotenv(Path(__file__).resolve().parent.parent / ".env")
#   resolves to backend/.env
# AFTER:  load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
#   resolves to repo-root/.env
```

```python
# backend/scripts/check-secrets.py — interface
# Usage: python backend/scripts/check-secrets.py [--json]
# Exit 0: all REQUIRED checks pass
# Exit 1: any REQUIRED check fails
# 
# --json output schema:
# {
#   "status": "ok" | "fail",
#   "failures": [{"var": "...", "reason": "missing|placeholder"}],
#   "warnings": [{"var": "...", "reason": "..."}],
#   "dead_vars": ["N8N_*", ...],
#   "crm_checks": [{"client": "...", "var": "...", "status": "ok|missing|placeholder"}]
# }
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `Settings` model_validator rejects missing CRITICAL secrets | Instantiate `Settings` without keys; assert `ValueError` |
| Unit | `Settings` model_validator rejects placeholder values | Pass `OPENAI_API_KEY=change-me-before-production`; assert error |
| Unit | `QORA_API_KEY` required in all envs | Instantiate without; assert fail |
| Unit | `is_weak_placeholder()` detects all patterns | Parametrized test with each placeholder |
| Unit | `validate_all_integration_credentials()` — active CRM, missing key | tmp_path crm.yaml; assert `SystemExit` |
| Unit | `validate_all_integration_credentials()` — disabled CRM skipped | `enabled: false` crm.yaml; assert no error |
| Unit | `validate_all_integration_credentials()` — no crm.yaml | Empty client dir; assert no error |
| Unit | `CRMConfig.enabled` defaults to `True` | Load existing crm.yaml; assert `enabled is True` |
| Unit | `check-secrets.py` exits 0 on valid env | subprocess with env vars set |
| Unit | `check-secrets.py` exits 1 on missing REQUIRED | subprocess without OPENAI_API_KEY |
| Unit | `check-secrets.py --json` returns valid JSON | Parse output |
| Unit | `check-secrets.py` detects dead vars | Verify N8N_*/TWILIO_* appear in dead_vars |
| Integration | `main.py` reads CORS/docs from `settings.*` | Grep for `os.getenv` in main.py; assert zero hits for declared vars |
| Integration | Lifespan startup fails when crm.yaml refs missing env var | `TestClient` with patched crm.yaml |
| Integration | `load_dotenv` resolves to root `.env` | Assert `main.py` path resolves outside `backend/` |
| Integration | Existing tests pass unchanged (conftest injects test keys) | Full test suite green |

**Strict TDD**: Write failing test first for each `@model_validator` scenario, then implement the validator. The `conftest.py` already injects `QORA_API_KEY` and both API keys, so existing tests will not break.

## Migration / Rollout

**Backward compatible.** All steps are additive or tighten existing implicit contracts.

| Step | Risk | Mitigation |
|------|------|------------|
| Add `@model_validator` for CRITICAL secrets | Breaks startup only if secrets were already absent (already broken at runtime) | conftest injects test keys |
| `QORA_API_KEY` now required | conftest already injects it; `.env.example` has it | Document in migration notes |
| `enabled: bool = True` in CRMConfig | Defaults `True`; existing crm.yaml files unchanged | No action needed |
| Replace `os.getenv()` in main.py | Same values from same env vars; zero behavior change | Unit test confirms |
| Delete `backend/.env` | Local dev must use root `.env` going forward | Clear message in PR description + runbook |
| Move `backend/.env.example` → root `.env.example` | Operators accustomed to old location | PR description notes the move; git tracks the rename |
| Update `load_dotenv()` paths in 3 files | Straightforward path change | Tests verify env vars load correctly |

**Docs cleanup**: Once B8 lands, all practical docs must stop telling users to edit `backend/.env`. The runbook (`docs/ops/secrets-management.md`) and root `.env.example` header will be the canonical references. Existing docs (README, setup guides) that mention `backend/.env` must be updated in the B8 docs PR slice.

**Rollback**: Revert `config.py` validator + `main.py` path and getenv calls + delete new files + restore `backend/.env.example`. No data migration, no schema change.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Operator discovers missing env var on first post-B8 deploy | Medium | Low — was already broken at runtime | `check-secrets.py` catches pre-deploy |
| Developer still creates `backend/.env` out of habit | Medium | Low — `load_dotenv` no longer reads it; app ignores it | Clear warning in runbook + PR description |
| CRM startup validation too aggressive for clients without integrations | Low | Low | Skip clients with no crm.yaml or `enabled: false` |
| Existing tests break from new required validators | Low | Medium | conftest already injects all needed keys |

## Review Workload Forecast

Estimated changed lines: ~500–650 (additions + deletions).

| PR Slice | Scope | Est. Lines | Reviewable Alone? |
|----------|-------|------------|-------------------|
| PR #1: Core validation | `config.py` validators, `credentials.py`, `crm_config.py` enabled field, lifespan hook, all unit tests | ~350 | Yes |
| PR #2: Tooling + env convention + docs | `check-secrets.py`, `.env.example` move+overhaul, `frontend/.env.example`, `load_dotenv` path updates in 3 files, `backend/.env` deletion, `docs/ops/secrets-management.md`, docs cleanup | ~250 | Yes |

Single PR is feasible at ~600 lines but splitting keeps each PR under the 400-line review budget. **Recommendation: 2 chained PRs.**

## Open Questions

- None — all user decisions have been incorporated.
