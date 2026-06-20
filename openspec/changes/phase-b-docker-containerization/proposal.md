# Proposal: Phase B Docker Containerization

## Intent

Qora can only run on a machine with Python, Node.js, uv, and npm installed. There is no way to ship the application as a self-contained unit. This blocks production deployment (Phase B2) and creates a fragile, manual setup story.

This change packages the full application — FastAPI backend + built React frontend — into a single Docker image so it can be started with `docker compose up` and later deployed to any cloud platform.

## Scope

### In Scope
- Multi-stage `Dockerfile` (Node build stage → Python runtime stage)
- `docker-compose.yml` — single service, named SQLite volume, env_file injection
- `.dockerignore` — exclude secrets, DB files, `.venv`, `node_modules`, `.git`
- `backend/app/main.py` delta — `StaticFiles` mount so FastAPI serves the built React app
- `docker/entrypoint.sh` — runs Alembic migration then starts uvicorn
- `backend/.env.example` delta — add `DATABASE_URL` Docker note
- Remove stale root-level `qora.db` (0 bytes, unused)

### Out of Scope
- VPS/cloud deployment (Phase B2)
- Auth, CORS, or secrets architecture changes
- PostgreSQL migration (Phase B3)
- ngrok integration inside Docker
- CI/CD pipeline
- Replacing `./Qora` local dev launcher

## Capabilities

### New Capabilities
- `docker-container-runtime`: Single-container image that runs the full Qora application with pre-start migrations, static frontend serving, and SQLite on a named volume.

### Modified Capabilities
None

## Approach

**Single container, multi-stage build.** A Node stage compiles `frontend/` into `dist/`. A Python stage installs backend deps with `uv`, copies both backend source and the frontend build, then launches via `entrypoint.sh` which runs `python scripts/migrate.py && uvicorn app.main:app`.

FastAPI serves the built React SPA via a catch-all `StaticFiles` mount at `/` (with `html=True` for React Router). API routes registered first take priority — no path conflicts.

SQLite lives on a named Docker volume (`qora-data`) at `/app/data/qora.db`. The `.env` file is injected at runtime via `env_file:`, never baked into the image.

Both workflows coexist: `./Qora` for hot-reload local dev, `docker compose up` for a production-like environment.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `Dockerfile` | New | Multi-stage: Node build + Python runtime |
| `docker-compose.yml` | New | Single service, volume, health check |
| `.dockerignore` | New | Exclude secrets, DB, build artifacts |
| `docker/entrypoint.sh` | New | Migration + uvicorn startup script |
| `backend/app/main.py` | Modified | Add `StaticFiles` mount for `/app/static-frontend/` |
| `backend/.env.example` | Modified | Add DATABASE_URL docker note |
| `qora.db` (root) | Removed | Stale 0-byte file, not used |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| SQLite WAL corruption on non-local Docker volume | Low | Use named volume on local disk only; document restriction |
| `.env` accidentally baked into image | Low | `.dockerignore` is mandatory; verify with `docker history` |
| Static mount path shadows API routes | Low | Register all API routes before `StaticFiles` mount |
| `uv.lock` version mismatch between dev and Docker `uv` | Low | Pin `uv` version in Dockerfile |
| Alembic backup guard blocks container restart | Med | Set `QORA_SKIP_BACKUP_CHECK=1` for Docker; document in compose file |

## Rollback Plan

Delete `Dockerfile`, `docker-compose.yml`, `.dockerignore`, and `docker/entrypoint.sh`. Revert the `StaticFiles` delta in `main.py`. The `./Qora` launcher and all existing workflows remain untouched throughout — nothing in the current dev path changes.

## Dependencies

- Docker Desktop (or Docker Engine + Compose plugin) installed on the target machine
- Alembic migration scripts already merged (PR #103 — B4 complete)

## Success Criteria

- [ ] `docker compose up --build` starts without errors
- [ ] `http://localhost:8000` serves the React frontend
- [ ] `http://localhost:8000/api/v1/health` returns HTTP 200
- [ ] `qora.db` survives a `docker compose down && docker compose up` cycle (volume persists)
- [ ] `docker history <image>` shows no `.env` or `qora.db` in layers
- [ ] `./Qora` still works after all files are added (dev workflow unchanged)

---

## Review Workload Forecast

| File | Est. lines |
|------|-----------|
| `Dockerfile` | ~50 |
| `docker-compose.yml` | ~25 |
| `.dockerignore` | ~20 |
| `docker/entrypoint.sh` | ~10 |
| `backend/app/main.py` | ~10 delta |
| `backend/.env.example` | ~5 delta |
| `qora.db` (root delete) | 0 |

**Total: ~120 changed lines — well within the 800-line budget. Single PR.**

## Open Questions / Decisions Required Before Spec

1. **Entrypoint file vs inline CMD** — exploration suggested starting with inline CMD; proposal upgrades to `entrypoint.sh` for clarity. Confirm this is acceptable or revert to CMD-only.
2. **`QORA_SKIP_BACKUP_CHECK` default** — should the compose file set this to `1` by default, or require explicit opt-in to skip the backup guard on every restart?
3. **Health check endpoint** — `/api/v1/health` is assumed to exist. Verify it does; if not, spec must include creating it.

## Next Recommended Phase

`sdd-spec` → define requirements and scenarios for `docker-container-runtime` capability, then `sdd-design` → file-level design for `Dockerfile` and `main.py` delta.
