# Design: Phase B Docker Containerization

## Technical Approach

Single-container multi-stage Docker build that packages FastAPI + built React frontend into one image. FastAPI serves the SPA via `StaticFiles` on `/`, API routes take priority by registration order. SQLite persists on a named volume. `docker/entrypoint.sh` runs migrations then execs uvicorn. Coexists with `./Qora` dev launcher — no existing workflows change.

## Architecture Decisions

| Decision | Choice | Alternatives | Rationale |
|----------|--------|-------------|-----------|
| Container strategy | Single container, FastAPI serves static files | Separate containers (nginx + backend) | One port, zero CORS, trivial at Qora's scale (~1 user). Split later if needed |
| Base images | `node:22-alpine` (build), `python:3.11-slim` (runtime) | `python:3.11-alpine` | `slim` has better glibc compat for Python C extensions; alpine would need musl workarounds |
| Package install | `pip install uv && uv sync --frozen --no-dev` | `pip install .` / `poetry` | Matches existing `uv.lock` workflow; `--frozen` ensures reproducible builds |
| Entrypoint | `docker/entrypoint.sh` with `set -e` + `exec` | Inline `CMD` chain | Dedicated script is clearer, extensible, and `exec` replaces shell with uvicorn (PID 1 signal handling) |
| Frontend path | `/app/static-frontend/` inside container | `/app/frontend/dist/` | Distinct name avoids confusion with source `frontend/` dir |
| DB location | `/app/data/qora.db` on named volume `qora-data` | Bind mount | Named volumes are Docker-managed, survive `down/up`, no host path coupling |
| Backup guard | `QORA_SKIP_BACKUP_CHECK=1` in compose env | Inline in `.env` | Container restarts must not block on missing backup; set explicitly in compose for visibility |
| Non-root user | `adduser --disabled-password --no-create-home qora` | Run as root | Security best practice; user owns `/app/data` for write access |
| Health check | `curl -f http://localhost:8000/api/v1/health` | `wget` / Python script | `curl` available in `python:3.11-slim`; endpoint already exists |

## Data Flow

```
docker compose up --build
        │
        ▼
┌── Stage 1: node:22-alpine ──┐
│  npm ci → npm run build     │
│  Output: /build/dist/       │
└─────────────┬───────────────┘
              │ COPY --from
              ▼
┌── Stage 2: python:3.11-slim ┐
│  uv sync --frozen --no-dev  │
│  COPY backend/* → /app/     │
│  COPY dist/ → /app/static-frontend/ │
│  USER qora                  │
└─────────────┬───────────────┘
              │ entrypoint.sh
              ▼
  python scripts/migrate.py
              │ success?
              ├─ no → exit 1 (container fails)
              ▼
  exec uvicorn app.main:app :8000
              │
    ┌─────────┼──────────┐
    ▼         ▼          ▼
  /api/v1/*  /demo/*    /* (SPA)
              │
    Volume: qora-data → /app/data/qora.db
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `Dockerfile` | Create | Multi-stage: node build + python runtime, non-root user |
| `docker-compose.yml` | Create | Single service, named volume, env_file, health check, restart policy |
| `.dockerignore` | Create | Exclude `.env`, `*.db`, `node_modules`, `.venv`, `__pycache__`, `.git` |
| `docker/entrypoint.sh` | Create | `set -e`, run migrate.py, `exec uvicorn` |
| `backend/app/main.py` | Modify | Add conditional `StaticFiles` mount at `/` for `/app/static-frontend/` (after all routes) |
| `backend/.env.example` | Modify | Add Docker section with `DATABASE_URL` note |
| `qora.db` (root) | Delete | Stale 0-byte file, not used by any workflow |

## Interfaces / Contracts

### StaticFiles mount in main.py (appended after line 298)

```python
# Static frontend — Docker production build (served only when dist exists)
_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "static-frontend")
if os.path.isdir(_FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
```

Key constraint: this mount MUST be the last `app.mount()` call. `html=True` enables SPA fallback (serves `index.html` for unmatched paths). API routes (`/api/v1/*`), demo mount (`/demo/*`), docs (`/docs`, `/redoc`), and admin redirect (`/admin`) are all registered before this — FastAPI/Starlette checks routes top-down, so they take priority.

The path resolves to `/app/static-frontend/` inside the container (two levels up from `app/main.py` is `/app/`, then `static-frontend/`). Outside Docker, the directory won't exist, so the mount is skipped — `./Qora` dev workflow is unaffected.

### docker/entrypoint.sh

```bash
#!/usr/bin/env bash
set -e

echo "Running database migrations..."
python scripts/migrate.py

echo "Starting Qora server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
```

`set -e` ensures migration failure stops the container. `exec` replaces the shell process so uvicorn receives SIGTERM directly from Docker.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Build | Image builds without errors | `docker compose build` exits 0 |
| Smoke | Frontend loads at `localhost:8000` | `curl -s localhost:8000 \| grep -q '<div id="root">'` |
| API | Health endpoint responds | `curl -f localhost:8000/api/v1/health` returns 200 |
| Persistence | DB survives restart | Write data → `down` → `up` → verify data exists |
| Security | No secrets in image layers | `docker history <image>` shows no `.env` |
| Isolation | `./Qora` still works | Run `./Qora` after adding Docker files |

## Migration / Rollout

No data migration required. Rollback: delete `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `docker/entrypoint.sh`, revert `main.py` StaticFiles delta and `.env.example` delta. The `./Qora` launcher is untouched throughout.

## Open Questions

None — all decisions were resolved in the proposal and spec phases.
