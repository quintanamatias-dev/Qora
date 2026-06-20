# Exploration: Phase B Docker Containerization

## Current State

Qora runs entirely locally via the `./Qora` launcher script, which starts three processes in parallel:

1. **Backend** — FastAPI/uvicorn on port 8000 (`python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`)
2. **Frontend** — Vite dev server on port 5173 (`npm run dev -- --host 0.0.0.0 --strictPort`)
3. **ngrok** — tunnels port 8000 to a public HTTPS URL for ElevenLabs webhooks

Before the backend starts, the launcher runs `python scripts/migrate.py` (Alembic upgrade head) to ensure the DB schema is current. The launcher also checks `.env` existence, `node_modules`, and performs port-clash cleanup.

There is **no Docker infrastructure** — no Dockerfile, docker-compose, or .dockerignore anywhere in the repo.

### Runtime Requirements

| Requirement | Backend | Frontend |
|---|---|---|
| **Language** | Python ≥3.11 | Node.js (v22 on dev machine) |
| **Package manager** | uv (lockfile: `uv.lock`) | npm (lockfile: `package-lock.json`) |
| **Build step** | None (source runs directly) | `tsc -b && vite build` → `frontend/dist/` |
| **Entry point** | `python -m uvicorn app.main:app` | Vite dev (dev) / static files (prod) |
| **Ports** | 8000 | 5173 (dev only) |
| **DB** | SQLite via aiosqlite, WAL mode | N/A |
| **Env vars** | `backend/.env` — pydantic-settings + dotenv | `VITE_API_BASE_URL` (empty = same-origin) |
| **Pre-start** | `python scripts/migrate.py` | N/A |

### Key Environment Variables (backend)

| Variable | Required | Notes |
|---|---|---|
| `OPENAI_API_KEY` | Yes | GPT-4o integration |
| `ELEVENLABS_API_KEY` | Yes | Voice agent |
| `ELEVENLABS_AGENT_ID` | Yes | Conversational AI agent ID |
| `ELEVENLABS_VOICE_ID` | Yes | Voice ID for TTS |
| `DATABASE_URL` | No | Default: `sqlite+aiosqlite:///./qora.db` |
| `QUINTANA_AIRTABLE_API_KEY` | No | CRM integration for pilot client |
| Various N8N_* | No | Currently unused in runtime |

### File Paths That Matter

| Path | Purpose | Docker impact |
|---|---|---|
| `backend/qora.db` | Production SQLite database (757KB, WAL mode) | Must be a mounted volume |
| `backend/.env` | Secrets | Must NOT be baked into image |
| `backend/alembic/` | Migration scripts | Bundled in image |
| `backend/alembic.ini` | Alembic config | Bundled in image |
| `backend/scripts/migrate.py` | Pre-start migration runner | Bundled in image |
| `backend/app/static/` | Demo voice page (`/demo/`) | Bundled in image |
| `backend/clients/` | Per-client prompt/knowledge files | Bundled in image (read-only at runtime) |
| `frontend/dist/` | Built React app | Built in multi-stage, served at runtime |
| Root `qora.db` | Empty file (0 bytes) — not used | Ignore |

## Affected Areas

- `Dockerfile` (new) — multi-stage build for backend + frontend
- `docker-compose.yml` (new) — service orchestration
- `.dockerignore` (new) — exclude .env, .venv, node_modules, .git
- `backend/.env.example` — may need a `docker` section/notes
- `Qora` launcher — coexists, not replaced
- `docs/ROADMAP.md` — mark B1 as in-progress

## Approaches

### Approach 1: Backend Serves Frontend Static Build (Recommended)

Single container: FastAPI serves both the API and the frontend static build (`frontend/dist/`). Multi-stage Dockerfile builds the frontend in a Node stage, copies `dist/` into the Python stage, and FastAPI mounts it as a `StaticFiles` endpoint.

- **Pros:**
  - Simplest deployment — one container, one port, one health check
  - No CORS issues — frontend and API are same-origin
  - No nginx/caddy config to maintain
  - `VITE_API_BASE_URL` stays empty (same-origin) — zero frontend config needed
  - Perfect for a VPS/Railway/Fly deploy (Phase B2)
  - Matches current user skill level (user has never deployed at this scale)
- **Cons:**
  - uvicorn serving static files is slower than nginx for high traffic (irrelevant at Qora's scale)
  - Frontend rebuild requires full container rebuild (mitigated by multi-stage cache)
  - Can't scale frontend and backend independently (not needed now)
- **Effort:** Low

### Approach 2: Separate Containers (Backend + Nginx Frontend)

Two containers in docker-compose: backend (FastAPI) and frontend (nginx serving `dist/` + reverse-proxy to backend API).

- **Pros:**
  - Professional architecture, scales independently
  - nginx is faster for static files and can handle SSL termination
  - Each service has its own resource limits
- **Cons:**
  - More complex — two Dockerfiles, nginx.conf, CORS config, inter-container networking
  - `VITE_API_BASE_URL` must be configured (or nginx must proxy `/api` to backend)
  - More moving parts to debug when something breaks
  - Overkill for current traffic (1 pilot client, no public users yet)
  - Higher cognitive load for user who is new to Docker
- **Effort:** Medium

### Approach 3: Single Container + Caddy Reverse Proxy

Like Approach 2 but using Caddy instead of nginx. Caddy handles SSL automatically and has simpler config.

- **Pros:**
  - Automatic HTTPS with Let's Encrypt
  - Simpler config than nginx
- **Cons:**
  - Still two containers and inter-container complexity
  - Caddy is less common in tutorials — harder to troubleshoot
  - SSL is typically handled by the cloud platform (Railway, Fly) anyway
- **Effort:** Medium

## Recommendation

**Approach 1: Backend Serves Frontend Static Build.**

Reasons:
1. **Simplicity** — one container, one port, zero CORS, zero proxy config. This is critical for a user who has never deployed at scale.
2. **Same-origin** — the frontend already works with `VITE_API_BASE_URL=""` (same-origin). No config change needed.
3. **Adequate performance** — uvicorn serving 787 bytes of `index.html` + hashed assets is perfectly fine at Qora's scale (single pilot client). Revisit in Phase E if traffic demands it.
4. **Migration path** — can always split into separate containers later without any backend code changes. The only change would be removing the `StaticFiles` mount and adding an nginx container.
5. **Cloud compatibility** — Railway, Fly.io, DigitalOcean App Platform, and Render all work best with single-container deploys.

### Proposed Architecture

```
┌──────────────────────────────────────────────┐
│  Docker Container (qora)                     │
│                                              │
│  ┌────────────────────────────────────────┐  │
│  │  FastAPI/uvicorn :8000                 │  │
│  │                                        │  │
│  │  /api/v1/*    → API routes             │  │
│  │  /demo/*      → static demo page       │  │
│  │  /*           → frontend/dist/ (React) │  │
│  └────────────────────────────────────────┘  │
│                                              │
│  Volume mount: /app/data/qora.db             │
│  Env: .env file or docker-compose env_file   │
└──────────────────────────────────────────────┘
```

### Proposed Dockerfile Strategy (Multi-Stage)

```
Stage 1: frontend-build
  FROM node:22-alpine
  WORKDIR /build
  COPY frontend/package*.json .
  RUN npm ci
  COPY frontend/ .
  RUN npm run build          # → /build/dist/

Stage 2: backend (production)
  FROM python:3.11-slim
  WORKDIR /app
  
  # Non-root user
  RUN adduser --disabled-password --no-create-home qora
  
  # Install uv, copy deps
  COPY backend/pyproject.toml backend/uv.lock ./
  RUN pip install uv && uv sync --frozen --no-dev
  
  # Copy application code
  COPY backend/app/ app/
  COPY backend/alembic/ alembic/
  COPY backend/alembic.ini .
  COPY backend/scripts/ scripts/
  COPY backend/clients/ clients/
  
  # Copy frontend build from stage 1
  COPY --from=frontend-build /build/dist/ /app/static-frontend/
  
  # Switch to non-root
  USER qora
  
  EXPOSE 8000
  
  # Pre-start migration + uvicorn
  CMD ["sh", "-c", "python scripts/migrate.py && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
```

### Proposed docker-compose.yml Structure

```yaml
services:
  qora:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - backend/.env
    volumes:
      - qora-data:/app/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s

volumes:
  qora-data:
```

### SQLite Volume Strategy

**Critical:** SQLite with WAL mode + Docker volumes requires careful handling.

1. **Named volume** (`qora-data`) — Docker manages the volume. The `qora.db`, `qora.db-shm`, and `qora.db-wal` files all live in this volume.
2. **DATABASE_URL override** — set to `sqlite+aiosqlite:////app/data/qora.db` so the DB lives in the mounted volume, NOT in the container filesystem.
3. **WAL mode and bind mounts** — bind mounts to a network filesystem (NFS, cloud volumes) can break WAL mode. Named Docker volumes on local disk are safe.
4. **Backup strategy** — the `_require_backup` guard in `scripts/migrate.py` checks for `qora.db.bak-YYYYMMDD`. In Docker, set `QORA_SKIP_BACKUP_CHECK=1` for automated restarts OR mount a volume with today's backup before running migrations manually.
5. **Single writer** — SQLite only supports one writer at a time. Docker Compose must NOT scale the `qora` service beyond 1 replica. Add `deploy.replicas: 1` to prevent accidents.

### Pre-Start Migration in Docker

The `CMD` approach is simplest:
```
CMD ["sh", "-c", "python scripts/migrate.py && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
```

Alternative: custom `entrypoint.sh` script that runs migration + starts uvicorn. Slightly more readable but adds a file.

Both work. For simplicity, start with the `CMD` approach. Promote to entrypoint script if more pre-start logic is needed later.

### Environment Variable Handling

1. **docker-compose `env_file`** — points to `backend/.env`. Secrets are injected from host, never baked into the image.
2. **Pydantic-settings** — already reads from environment variables. The `load_dotenv()` call in `main.py` loads from `backend/.env`. In Docker, env vars are injected by compose, so `load_dotenv()` finding no `.env` file is fine — pydantic-settings reads env vars directly.
3. **`.env` file NOT in image** — `.dockerignore` must exclude `.env`, `*.db`, `.venv/`, `node_modules/`, `.git/`.
4. **`DATABASE_URL`** — must be set in `.env` or compose environment to point to the volume-mounted path: `sqlite+aiosqlite:////app/data/qora.db`.

### Frontend Serving Details

FastAPI needs a new `StaticFiles` mount for the built React app. Two options:

**Option A: Catch-all mount at root (recommended)**
```python
# After all API routes
if os.path.isdir("/app/static-frontend"):
    app.mount("/", StaticFiles(directory="/app/static-frontend", html=True), name="frontend")
```
The `html=True` flag makes it serve `index.html` for any path not matched by API routes — needed for React Router client-side routing.

**Option B: Dedicated `/app` prefix**
Mount at `/app` instead of `/`. Avoids any path conflicts but changes the frontend URLs.

Option A is correct because it mirrors how React SPAs are typically deployed. The API routes (`/api/v1/*`, `/demo/*`, `/docs`, `/redoc`) are registered first, so they take priority. Any unmatched path falls through to the static frontend.

### Local Dev Workflow

Docker should **coexist** with the `./Qora` launcher, NOT replace it.

- **`./Qora`** — local dev with hot reload (uvicorn `--reload`, Vite HMR). Fast iteration loop.
- **`docker compose up`** — production-like environment. Tests the built frontend, migration flow, volume mounts. Slower iteration (rebuild on change).
- **ngrok** — stays outside Docker. The Qora launcher uses it for local dev. For production (Phase B2), the cloud platform provides a public URL.

### File Organization

```
Qora/                          (project root)
├── Dockerfile                 ← NEW — multi-stage build
├── docker-compose.yml         ← NEW — service orchestration
├── .dockerignore              ← NEW — exclude secrets, DBs, .venv, node_modules
├── Qora                       ← existing launcher (unchanged)
├── backend/
│   ├── .env                   ← secrets (excluded from image)
│   ├── .env.example           ← update with Docker notes
│   └── ...
└── frontend/
    └── ...
```

All Docker files at the project root — the Dockerfile needs access to both `backend/` and `frontend/` for the multi-stage build. Putting Dockerfile inside `backend/` would break the frontend build context.

### Review Workload Forecast

| File | Est. lines | Notes |
|---|---|---|
| `Dockerfile` | ~50 | Multi-stage, two stages |
| `docker-compose.yml` | ~25 | Single service + volume |
| `.dockerignore` | ~20 | Standard exclusions |
| `backend/app/main.py` | ~10 (delta) | Add StaticFiles mount for frontend |
| `backend/.env.example` | ~5 (delta) | Add DATABASE_URL Docker note |
| `docs/ROADMAP.md` | ~2 (delta) | Mark B1 in-progress |

**Total estimated: ~112 changed lines** — well within the 800-line review budget. Single PR is appropriate.

## Risks

1. **SQLite WAL + Docker volume corruption** — If Docker uses an overlay filesystem or network-attached storage for the volume, WAL mode can corrupt the database. Mitigation: use named Docker volumes on local disk; document this explicitly.

2. **`.env` file accidentally baked into image** — If `.dockerignore` is missing or wrong, secrets end up in the image layers. Mitigation: `.dockerignore` is a mandatory deliverable; verify with `docker history`.

3. **Frontend static mount path conflicts** — If the React app has routes that collide with API paths (e.g., `/docs`), the static fallback could shadow them. Mitigation: API routes are registered first and take priority; React routes use `/admin/*` which doesn't conflict.

4. **`load_dotenv()` finds no file in Docker** — Currently `main.py` calls `load_dotenv(backend/.env)`. In Docker, the `.env` file isn't in the image. `load_dotenv()` silently succeeds when the file is missing (`override=False`), and pydantic-settings reads env vars from the container environment. This is safe — but should be documented.

5. **uv lock format** — `uv sync --frozen` requires `uv.lock` format compatibility. If the Docker `uv` version differs from dev, the lock file may not parse. Mitigation: pin `uv` version in Dockerfile, or fall back to `pip install .` for initial simplicity.

6. **Root-level `qora.db` (0 bytes)** — There's a stale empty `qora.db` at the project root. The real DB is `backend/qora.db`. This is a minor confusion risk — consider removing the root one in a cleanup. Not a Docker blocker.

## Non-Goals

- **PostgreSQL migration** (B3) — separate Phase B item. Docker prep should work with SQLite first.
- **SSL/HTTPS termination** — handled by the cloud platform in Phase B2, not by Docker.
- **CI/CD pipeline** — future work. This slice is local Docker only.
- **Multi-replica scaling** — SQLite doesn't support it. Single container.
- **ngrok in Docker** — ngrok stays outside Docker for local dev. Production gets a real URL.
- **Production deployment** (B2) — separate slice. This is containerization only.

## Ready for Proposal

**Yes** — the exploration is complete. The recommended approach (single container, backend serves frontend, multi-stage build) is clear, simple, and well within the review budget. The orchestrator should proceed to `sdd-propose` with:

- Change name: `phase-b-docker-containerization`
- Approach: Single container, backend serves frontend static build
- Scope: Dockerfile, docker-compose.yml, .dockerignore, small main.py delta for static frontend mount
- Est. review size: ~112 lines (single PR)
