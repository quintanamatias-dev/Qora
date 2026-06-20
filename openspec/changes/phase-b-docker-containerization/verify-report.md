# Verification Report: phase-b-docker-containerization

**Mode**: Strict TDD verification  
**Date**: 2026-06-20  
**Verdict**: FAIL

## Completeness

| Dimension | Result | Evidence |
|---|---:|---|
| Proposal/spec/design/tasks read | ✅ | `proposal.md`, `spec.md`, `design.md`, `tasks.md` read from OpenSpec. `apply-progress` read from Engram observation `#1964`. |
| Task completion | ✅ | `tasks.md` and apply-progress show all tasks checked. |
| Ruff on changed Python files | ❌ | `uv run ruff check app/main.py tests/unit/test_docker_config.py` failed: unused `pytest` import in `tests/unit/test_docker_config.py:17`. |
| Focused Docker config tests | ✅ | `python3 -m pytest tests/unit/test_docker_config.py -q` → `55 passed in 0.03s`. |
| Full backend suite | ✅ | `python3 -m pytest tests/ -q` → `2428 passed, 7 warnings in 53.85s`. |
| Docker build | ✅ | `docker compose build` → `qora:latest Built`. |
| Compose runtime smoke | ✅ | `docker compose up -d`; health reached `healthy`; `/`, `/some/nested/route`, `/api/v1/health` returned HTTP 200. |
| SQLite persistence | ✅ | Wrote marker row inside `/app/data/qora.db`; after `docker compose down && docker compose up -d`, marker count remained `1`. |
| `./Qora` dev workflow | ✅ | Local launcher smoke test reached backend health and frontend HTTP 200. |
| Stale root DB deleted | ✅ | `test ! -e qora.db` at repo root passed. |
| No secrets/DB in image layers | ❌ | `docker history --no-trunc qora:latest` had no forbidden tokens, but image filesystem scan found DB files under `/app`: `/app/qora.db`, `/app/qora.db-wal`, `/app/qora.db-shm`, `/app/verify_atomicity.db`, `/app/verify_missing_client.db`, `/app/verify_corrections.db`. |
| `.dockerignore` correctness | ❌ | File exists and excludes required top-level patterns, but DB files from `backend/` were still copied into the image. Current DB ignore patterns are not sufficient for nested backend DB artifacts. |

## Strict TDD Compliance

| Check | Result | Details |
|---|---:|---|
| TDD evidence reported | ✅ | Engram apply-progress contains `TDD Cycle Evidence`. |
| All tasks have tests | ✅ | Docker config coverage reported in `backend/tests/unit/test_docker_config.py`. |
| RED confirmed | ✅ | Test file exists and covers Docker config/static serving assertions. |
| GREEN confirmed | ✅ | Focused Docker config tests passed: `55 passed`. |
| Triangulation adequate | ✅ | Additional cases present for dockerignore, entrypoint, Dockerfile, compose, and static frontend routing. |
| Safety net for modified code | ✅ | Full backend suite passed. |

**Assertion quality**: ✅ No tautologies or empty ghost-loop assertions found in `backend/tests/unit/test_docker_config.py` during source inspection.

## Spec Compliance Matrix

| Requirement / Scenario | Status | Runtime Evidence |
|---|---:|---|
| Image Build / Successful build | ✅ PASS | `docker compose build` completed successfully. |
| Image Build / Build fails on missing frontend source | ⚠️ NOT RERUN | Not destructive-tested during final verification. Dockerfile does run `npm run build`, so missing source should fail. |
| Static Frontend / React app loads | ✅ PASS | `GET /` returned HTTP 200 with React root. |
| Static Frontend / Deep-link | ✅ PASS | `GET /some/nested/route` returned HTTP 200 with React root. |
| Static Frontend / API priority | ✅ PASS | `GET /api/v1/health` returned JSON health response, not SPA HTML. |
| Entrypoint Migration / success then server starts | ✅ PASS | Compose startup completed and health passed after migrations. |
| Entrypoint Migration / migration failure blocks server | ⚠️ NOT RERUN | `entrypoint.sh` uses `set -e` and `python scripts/migrate.py` before `exec uvicorn`; no failure injection performed. |
| SQLite Volume Persistence / data persists | ✅ PASS | Marker persisted across compose down/up cycle on named volume. |
| SQLite Volume Persistence / fresh start creates DB | ✅ PASS | Container started healthy with `/app/data/qora.db` on named volume. |
| Environment Injection / `.env` not baked | ❌ FAIL | `.env` was not found, but DB artifacts were baked into the image, violating the same no-runtime-data-in-image requirement. |
| Environment Injection / missing `.env` fails runtime | ⚠️ NOT RERUN | Not rerun because local `.env` is present and verification avoided altering it. |
| Health Check / passes after startup | ✅ PASS | Docker health status reached `healthy`. |
| Health Check / fails when server down | ⚠️ NOT RERUN | No uvicorn failure injection performed. |
| Dockerignore Exclusions / sensitive files excluded | ❌ FAIL | Nested backend DB files are present in the image. |
| Single-Port Compose Startup | ✅ PASS | Frontend and API reachable on port 8000 only. |
| Dev Workflow Isolation | ✅ PASS | `./Qora` smoke verified backend and frontend readiness. |
| Stale Root DB Removal | ✅ PASS | Root `qora.db` absent and Docker did not recreate root DB. |

## Design Coherence

| Decision | Status | Notes |
|---|---:|---|
| Single container serving API + SPA | ✅ | Verified through compose HTTP checks. |
| Multi-stage Node + Python image | ✅ | Dockerfile and build evidence match. |
| `uv sync --frozen --no-dev` | ✅ | Dockerfile uses frozen production dependency sync. |
| Entrypoint with migration then `exec uvicorn` | ✅ | Entrypoint matches design and tests pass. |
| SQLite named volume at `/app/data` | ✅ | Compose + persistence check pass. |
| Non-root runtime user | ✅ | Dockerfile switches to `USER qora`. |
| Exclude runtime data from image | ❌ | Backend DB artifacts are copied into `/app`. |
| Dev workflow unchanged | ✅ | `./Qora` smoke test passed. |

## Command Evidence

| Command | Exit | Evidence |
|---|---:|---|
| `uv run ruff check app/main.py tests/unit/test_docker_config.py` | 1 | `F401 pytest imported but unused` at `tests/unit/test_docker_config.py:17`. |
| `python3 -m pytest tests/unit/test_docker_config.py -q` | 0 | `55 passed in 0.03s`. |
| `python3 -m pytest tests/ -q` | 0 | `2428 passed, 7 warnings in 53.85s`. |
| `docker compose build` | 0 | `qora:latest Built`. |
| `docker compose up -d` + health wait | 0 | `health=healthy`. |
| HTTP smoke + marker insert | 0 | `/`, deep-link, and health all HTTP 200; marker inserted. |
| `docker compose down && docker compose up -d` + marker query | 0 | `health=healthy; persistence_marker_count=1`. |
| `docker history --no-trunc qora:latest` token scan | 0 | No `.env`, `qora.db`, `DATABASE_URL=`, `SECRET`, or `API_KEY` tokens found. |
| Image filesystem DB/env scan | 1 | Found DB files in `/app`. |
| `./Qora` smoke | 0 | `qora_dev_backend=ready; qora_dev_frontend=ready`. |
| `test ! -e qora.db` | 0 | Root DB absent. |

## Issues

### CRITICAL

1. **Ruff failure blocks verification**  
   `backend/tests/unit/test_docker_config.py` imports `pytest` but does not use it. Strict verification requires Ruff on changed files to pass.

2. **Database files are baked into the Docker image**  
   Final image contains `/app/qora.db`, `/app/qora.db-wal`, `/app/qora.db-shm`, `/app/verify_atomicity.db`, `/app/verify_missing_client.db`, and `/app/verify_corrections.db`. This violates the spec's Dockerignore Exclusions and no DB/runtime data in image requirements.

3. **`.dockerignore` does not protect nested backend DB artifacts**  
   Current patterns include `*.db`, `*.db-wal`, and `*.db-shm`, but the build still copied DB files from `backend/` into `/app`. The ignore rules need recursive/backend-specific DB exclusions.

### WARNING

1. Docker build succeeded, but `adduser` printed interactive prompt text during build. It did not fail, but it is noisy and may be worth making explicitly non-interactive later.

2. Some negative scenarios were not failure-injection tested in final verification: missing frontend source, migration failure, missing `.env`, and unhealthy transition after uvicorn crash.

### SUGGESTION

- Add a focused test that proves nested DB files such as `backend/qora.db` and `backend/*.db-wal` are excluded by `.dockerignore`; the current tests only assert pattern presence, not effective recursive coverage.

## Final Verdict

**FAIL** — runtime behavior mostly works, but verification is blocked by Ruff failure and a security/data-packaging violation: DB files are present inside the Docker image.
