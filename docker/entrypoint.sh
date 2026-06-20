#!/usr/bin/env bash
# =============================================================================
# docker/entrypoint.sh — Qora container entrypoint
# =============================================================================
# 1. Runs Alembic migrations via python scripts/migrate.py.
#    set -e ensures the container exits with a non-zero code if migrations fail,
#    preventing uvicorn from starting against a mismatched schema.
# 2. Replaces the shell process with uvicorn via exec (PID 1) so Docker
#    SIGTERM is forwarded directly to uvicorn for graceful shutdown.
# =============================================================================

set -e

echo "Running database migrations..."
python scripts/migrate.py

echo "Starting Qora server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
