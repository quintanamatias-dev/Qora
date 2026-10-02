#!/usr/bin/env bash
# =============================================================================
# docker/entrypoint.sh — Qora container entrypoint
# =============================================================================
# 0. When started as root, makes the data volume writable by the qora user
#    (Railway mounts volumes as root) and re-executes itself as qora.
# 1. Runs Alembic migrations via python scripts/migrate.py.
#    set -e ensures the container exits with a non-zero code if migrations fail,
#    preventing uvicorn from starting against a mismatched schema.
# 2. Replaces the shell process with uvicorn via exec (PID 1) so Docker
#    SIGTERM is forwarded directly to uvicorn for graceful shutdown.
#    Listens on $PORT when the platform provides it (Railway), else 8000.
# =============================================================================

set -e

DATA_DIR="${QORA_DATA_DIR:-/app/data}"

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$DATA_DIR"
    chown -R qora:qora "$DATA_DIR"
    exec setpriv --reuid=qora --regid=qora --init-groups "$0" "$@"
fi

echo "Running database migrations..."
python scripts/migrate.py

echo "Starting Qora server..."
# --proxy-headers: trust X-Forwarded-Proto/For from the platform edge proxy so
# the app sees the original https scheme and client address.
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --proxy-headers \
    --forwarded-allow-ips="*"
