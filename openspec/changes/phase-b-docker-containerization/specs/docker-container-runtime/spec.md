# docker-container-runtime Specification

## Purpose

Defines requirements for packaging and running the full Qora application (FastAPI backend + built React frontend) as a single Docker container, accessible on a single port, with SQLite data persisted on a named volume.

---

## Requirements

### Requirement: Image Build

The build system MUST produce a single Docker image from a multi-stage Dockerfile. The Node stage MUST compile the React frontend into a static bundle. The Python stage MUST install backend dependencies and copy both backend source and the built frontend bundle.

#### Scenario: Successful build

- GIVEN the repository root contains a valid `Dockerfile` and `frontend/` source
- WHEN `docker compose up --build` is executed
- THEN the image builds without errors and exits stage 0

#### Scenario: Build fails on missing frontend source

- GIVEN the `frontend/` directory is absent or `npm run build` fails
- WHEN `docker compose up --build` is executed
- THEN the build step fails with a non-zero exit code and no runnable image is produced

---

### Requirement: Static Frontend Serving

The running container MUST serve the built React SPA on `/` via FastAPI's `StaticFiles` mount. API routes registered before the static mount MUST take priority over any path conflict.

#### Scenario: React app loads

- GIVEN the container is running
- WHEN a browser requests `http://localhost:8000/`
- THEN the React application HTML is returned with HTTP 200

#### Scenario: React Router deep-link

- GIVEN the container is running
- WHEN a browser requests `http://localhost:8000/some/nested/route`
- THEN the React `index.html` is returned (html=True fallback) with HTTP 200

#### Scenario: API route takes priority

- GIVEN the container is running
- WHEN a request is made to `http://localhost:8000/api/v1/health`
- THEN the API handler responds — not the static file mount

---

### Requirement: Entrypoint Migration

The container entrypoint MUST run Alembic database migrations before starting the application server. If the migration step fails, the container MUST exit with a non-zero code and the server MUST NOT start.

#### Scenario: Migration succeeds then server starts

- GIVEN the container starts with a valid database path
- WHEN `entrypoint.sh` executes
- THEN migrations run to completion and uvicorn starts on port 8000

#### Scenario: Migration fails

- GIVEN the migration script encounters an error
- WHEN `entrypoint.sh` executes
- THEN the container exits with a non-zero code and uvicorn does not start

---

### Requirement: SQLite Volume Persistence

The SQLite database MUST be stored on a named Docker volume (`qora-data`) mounted at a path inside the container. The database file MUST survive a full `docker compose down && docker compose up` cycle.

#### Scenario: Data persists across restart

- GIVEN the container has been running and data was written to the database
- WHEN `docker compose down` is followed by `docker compose up`
- THEN previously written data is readable without re-seeding

#### Scenario: Fresh start creates database

- GIVEN no prior volume exists
- WHEN the container starts for the first time
- THEN migrations create the schema on the new volume and the container starts normally

---

### Requirement: Environment Variable Injection

Secrets and runtime configuration MUST be injected via `env_file:` in `docker-compose.yml`. The `.env` file MUST NOT be copied into the image at build time. `QORA_SKIP_BACKUP_CHECK` MUST be set to `1` by default in the compose file.

#### Scenario: .env not baked into image

- GIVEN a built image
- WHEN `docker history <image>` is inspected
- THEN no layer contains the contents of `.env` or any secret value

#### Scenario: Missing .env at runtime

- GIVEN `docker-compose.yml` references `env_file: .env` and the file does not exist
- WHEN `docker compose up` is executed
- THEN Docker reports an error about the missing env file before the container starts

---

### Requirement: Health Check

The compose service MUST define a health check that polls `http://localhost:8000/api/v1/health`. The container MUST be reported `healthy` once that endpoint returns HTTP 200.

#### Scenario: Health check passes after startup

- GIVEN the container has fully started
- WHEN Docker's health check interval elapses
- THEN `docker ps` shows the container status as `healthy`

#### Scenario: Health check fails when server is down

- GIVEN the uvicorn process has crashed inside the container
- WHEN Docker's health check interval elapses
- THEN the container status transitions to `unhealthy`

---

### Requirement: Dockerignore Exclusions

The `.dockerignore` file MUST exclude `.env`, `*.db`, `node_modules/`, `.venv/`, `__pycache__/`, and `.git/` from the build context. These files MUST NOT appear in any image layer.

#### Scenario: Sensitive files excluded

- GIVEN a `.dockerignore` listing `.env` and `*.db`
- WHEN the image is built in a directory containing `.env` and `qora.db`
- THEN those files are absent from the build context and from all image layers

---

### Requirement: Single-Port Compose Startup

`docker compose up` MUST start the full application (API + frontend) on a single port (8000). No additional port mappings or companion containers are required.

#### Scenario: Full app reachable on one port

- GIVEN `docker compose up` completes without error
- WHEN a user opens `http://localhost:8000`
- THEN both the React UI and the API are reachable on that single port

---

### Requirement: Dev Workflow Isolation

The `./Qora` local dev launcher MUST remain fully functional after all Docker files are added. Docker configuration files MUST NOT modify the local Python or Node dev environment.

#### Scenario: ./Qora works after adding Docker files

- GIVEN all Docker files (`Dockerfile`, `docker-compose.yml`, `.dockerignore`, `docker/entrypoint.sh`) have been committed
- WHEN a developer runs `./Qora`
- THEN the local dev server starts normally with hot-reload, unchanged from before

---

### Requirement: Stale Root DB Removal

The stale root-level `qora.db` file (0 bytes, not used by any workflow) MUST be deleted from the repository. It MUST NOT reappear via Docker volume mounts or entrypoint scripts.

#### Scenario: Root qora.db absent after cleanup

- GIVEN the file `qora.db` exists at the repository root with 0 bytes
- WHEN the cleanup commit is applied
- THEN `qora.db` no longer exists at the repository root

#### Scenario: Docker does not recreate root qora.db

- GIVEN the container is running with the volume mounted at `/app/data/qora.db`
- WHEN the container starts and entrypoint runs
- THEN no `qora.db` file is created at the repository root on the host
