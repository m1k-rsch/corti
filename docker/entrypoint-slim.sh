#!/usr/bin/env bash
set -euo pipefail

# ── Corti slim container entrypoint ───────────────────────────────
# Runs as root.  Performs:
#   1. Fix ownership on mounted volume.
#   2. Copy default config files if missing.
#   3. Validate required DB_* env vars.
#   4. exec corti server start as the 'app' user.

DATA_DIR="${CORTI_ROOT:-/home/app/.corti}"

# ── Step 1: Ensure required directories exist ────────────────────
mkdir -p "${DATA_DIR}/.index/sqlite"
mkdir -p "${DATA_DIR}/.tmp"

# ── Step 2: Fix ownership on mounted volume ──────────────────────
if [ "$(id -u)" = "0" ]; then
    echo "[entrypoint] Fixing volume ownership..."
    # Volume root belongs to the app user (it must create the data tree
    # default_app/... and the integrations sentinel there); config files
    # are chowned back to the host user who owns the volume so they can
    # edit ~/.corti/corti.toml (file write permission suffices).
    HOST_UID="$(stat -c '%u' "${DATA_DIR}" 2>/dev/null || echo 1000)"
    HOST_GID="$(stat -c '%g' "${DATA_DIR}" 2>/dev/null || echo 1000)"
    chown -R app:app "${DATA_DIR}"
    chown "${HOST_UID}:${HOST_GID}" "${DATA_DIR}/corti.toml" "${DATA_DIR}/ome.toml" 2>/dev/null || true
fi

# ── Step 3: Copy default config files if missing ─────────────────
if [ ! -f "${DATA_DIR}/corti.toml" ]; then
    echo "[entrypoint] Creating corti.toml from defaults..."
    cp /opt/corti/config/default.toml "${DATA_DIR}/corti.toml"
    chown app:app "${DATA_DIR}/corti.toml"
fi

if [ ! -f "${DATA_DIR}/ome.toml" ]; then
    echo "[entrypoint] Creating ome.toml from defaults..."
    cp /opt/corti/config/default_ome.toml "${DATA_DIR}/ome.toml"
    chown app:app "${DATA_DIR}/ome.toml"
fi

# ── Step 4: Validate external PG connectivity ────────────────────
: "${DB_HOST:?DB_HOST is required for slim mode — set via docker run -e DB_HOST=...}"
: "${DB_PORT:?DB_PORT is required}"
: "${DB_NAME:?DB_NAME is required}"
: "${DB_USER:?DB_USER is required}"
: "${DB_PASSWORD:?DB_PASSWORD is required}"

# ── Step 5: Launch corti ─────────────────────────────────────────
echo "[entrypoint] Starting corti server (slim, external PG at ${DB_HOST}:${DB_PORT}/${DB_NAME})..."
exec su -s /bin/bash app -c "exec /opt/corti/venv/bin/corti server start --host 0.0.0.0 --port 5473 --root '${DATA_DIR}' --log-level INFO"
