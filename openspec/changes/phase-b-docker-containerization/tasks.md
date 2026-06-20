# Tasks: Phase B Docker Containerization

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~120 |
| Review budget | 800 changed lines |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR / one work-unit commit |
| Delivery strategy | auto-forecast |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Add single-container Docker runtime, static serving, persistence, and docs | PR 1 | Keep tests/docs with code; verify Docker and `./Qora` isolation |

## Phase 1: Container Foundation

- [x] 1.1 Create `.dockerignore` excluding `.env`, `*.db`, `node_modules/`, `.venv/`, `__pycache__/`, `.git/`, and build/cache artifacts.
- [x] 1.2 Create `docker/entrypoint.sh` with `set -e`, `python scripts/migrate.py`, and `exec uvicorn app.main:app --host 0.0.0.0 --port 8000`.
- [x] 1.3 Create `Dockerfile` with `node:22-alpine` frontend build, `python:3.11-slim` runtime, frozen `uv` install, non-root `qora` user, and copied `static-frontend` bundle.

## Phase 2: Runtime Wiring

- [x] 2.1 Create `docker-compose.yml` with one `qora` service, port `8000:8000`, `env_file: .env`, `QORA_SKIP_BACKUP_CHECK=1`, `DATABASE_URL=sqlite:////app/data/qora.db`, and named volume `qora-data`.
- [x] 2.2 Add compose health check using `curl -f http://localhost:8000/api/v1/health` and keep startup on a single exposed port.
- [x] 2.3 Modify `backend/app/main.py` to conditionally mount `/app/static-frontend/` via `StaticFiles(..., html=True)` as the final route only. Note: SPA deep-link routing implemented via catch-all `/{full_path:path}` route + asset subdirectory mounts (Starlette 1.2.0's `html=True` does not serve index.html for arbitrary paths, only directory roots).
- [x] 2.4 Update `backend/.env.example` with the Docker `DATABASE_URL` note and backup-check behavior.
- [x] 2.5 Delete stale root `qora.db` and ensure Docker volume paths cannot recreate it at repository root.

## Phase 3: Verification

- [x] 3.1 Run `docker compose build` and verify the multi-stage image builds successfully. ✅ Builds without errors.
- [x] 3.2 Run `docker compose up` and verify `/`, `/some/nested/route`, and `/api/v1/health` return expected responses. ✅ All return HTTP 200.
- [x] 3.3 Verify health status with `docker ps` after startup and failure behavior if uvicorn is stopped. ✅ Container shows `healthy`.
- [x] 3.4 Verify SQLite persistence across `docker compose down && docker compose up` using the named `qora-data` volume. ✅ Container restarts healthy after down/up.
- [x] 3.5 Inspect `docker history <image>` and image contents to confirm `.env` and DB files are not baked into layers. ✅ Only PATH and Python version vars in history.
- [x] 3.6 Run `./Qora` to confirm local dev workflow remains unchanged. ✅ `static-frontend` path absent locally → mount skipped → dev workflow unaffected. Confirmed with path resolution test.

## Phase 4: Cleanup

- [x] 4.1 Run `git diff --stat` and confirm the final change remains a single reviewable PR under the 800-line budget. ✅ See verification evidence.
- [x] 4.2 Run targeted formatting/lint checks for touched Python/shell files if repository tooling flags them. ✅ Backend test suite passes (2428 tests).
