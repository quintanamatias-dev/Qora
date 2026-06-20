# =============================================================================
# Dockerfile — Qora multi-stage build
# =============================================================================
# Stage 1 (build):  node:22-alpine  — compiles React frontend into static bundle
# Stage 2 (runtime): python:3.11-slim — runs FastAPI + serves the built frontend
#
# Usage:
#   docker compose up --build
#
# The built image serves both the API (/api/v1/*) and the React SPA (/)
# on a single port (8000). SQLite lives on the named volume qora-data.
# =============================================================================


# -----------------------------------------------------------------------------
# Stage 1: Frontend build
# -----------------------------------------------------------------------------
FROM node:22-alpine AS frontend-build

WORKDIR /build

# Copy package manifests first for layer caching
COPY frontend/package.json frontend/package-lock.json ./

# Install all dependencies (including devDependencies needed for the build)
RUN npm ci

# Copy the rest of the frontend source
COPY frontend/ ./

# Compile TypeScript + Vite bundle → dist/
RUN npm run build


# -----------------------------------------------------------------------------
# Stage 2: Python runtime
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

# Install curl for the Docker health check
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv (pinned version for reproducible builds)
RUN pip install --no-cache-dir uv==0.7.12

WORKDIR /app

# Add the uv-managed venv to PATH so python/uvicorn/alembic resolve correctly
# in the entrypoint without needing to activate the venv explicitly.
ENV PATH="/app/.venv/bin:$PATH"

# Copy Python dependency manifests + README (required by hatchling build metadata)
# for layer caching — source changes don't invalidate the uv sync layer
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./

# Install production dependencies only (frozen = exact versions from uv.lock)
RUN uv sync --frozen --no-dev

# Copy the full backend source (after uv sync for layer caching)
COPY backend/ ./

# Copy the compiled React bundle from Stage 1 into the expected static path.
# main.py looks for /app/static-frontend/ to conditionally mount StaticFiles.
COPY --from=frontend-build /build/dist/ ./static-frontend/

# Create a non-root user for security — owns /app/data for SQLite writes
RUN adduser --disabled-password --no-create-home qora \
    && mkdir -p /app/data \
    && chown -R qora:qora /app/data

# Ensure the entrypoint script is executable
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Switch to non-root user
USER qora

# SQLite volume mount point — must match DATABASE_URL in docker-compose.yml
VOLUME ["/app/data"]

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
