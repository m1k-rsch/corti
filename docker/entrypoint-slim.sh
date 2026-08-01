#!/usr/bin/env bash
set -euo pipefail

# ── Corti slim container entrypoint ───────────────────────────────
# Runs as root.  Performs:
#   1. Resolve the host user (uid/gid) that owns the mounted volume.
#   2. Fix ownership on mounted volume.
#   3. Copy default config files if missing.
#   4. Validate required DB_* env vars.
#   5. exec corti server start as the 'app' user.

DATA_DIR="${CORTI_ROOT:-/home/app/.corti}"

# ── Step 1: Resolve the host user (uid/gid) ────────────────────────────
# The mounted volume's ROOT is chowned to the app user on every boot (the
# app must create its data tree default_app/... and the integrations
# sentinel there), so the root itself can NOT be used to rediscover the
# host user on the 2nd boot — it would report the app uid (998) and the
# config files would be chowned away from the host user, breaking the
# documented "edit corti.toml → docker restart" flow (F13, V9). Probe in
# order of stability:
#   1. a persisted marker (.host-user, written on first boot)
#   2. the config file itself (host-owned on every boot after the first)
#   3. the volume root (only valid on the very first boot, pre-chown)
HOST_UID=""
HOST_GID=""
MARKER="${DATA_DIR}/.host-user"
APP_UID="$(id -u app 2>/dev/null || echo 998)"
if [ -f "${MARKER}" ]; then
    IFS=':' read -r HOST_UID HOST_GID < "${MARKER}" || true
fi
if [ -z "${HOST_UID}" ] && [ -f "${DATA_DIR}/corti.toml" ]; then
    HOST_UID="$(stat -c '%u' "${DATA_DIR}/corti.toml" 2>/dev/null || true)"
    HOST_GID="$(stat -c '%g' "${DATA_DIR}/corti.toml" 2>/dev/null || true)"
fi
if [ -z "${HOST_UID}" ]; then
    HOST_UID="$(stat -c '%u' "${DATA_DIR}" 2>/dev/null || echo 1000)"
    HOST_GID="$(stat -c '%g' "${DATA_DIR}" 2>/dev/null || echo 1000)"
fi
# Persist for future boots — unless the probe only found the app user
# itself (an install that was chowned to 998 by a pre-V10 image): in that
# case do NOT cement a wrong marker; the host can fix ownership once and
# the next boot re-probes correctly.
if [ "$(id -u)" = "0" ] && [ -n "${HOST_UID}" ] && [ "${HOST_UID}" != "${APP_UID}" ]; then
    echo "${HOST_UID}:${HOST_GID}" > "${MARKER}" 2>/dev/null || true
fi
if [ "${HOST_UID}" = "${APP_UID}" ]; then
    echo "[entrypoint] WARNING: cannot determine the host user (probe returned the app uid ${APP_UID})."
    echo "[entrypoint] If you cannot edit ${DATA_DIR}/corti.toml, fix ownership once from the host:"
    echo "[entrypoint]   sudo chown -R <your-user>:<your-group> ~/.corti   # then docker restart corti"
fi

# ── Step 2: Ensure required directories exist ────────────────────
mkdir -p "${DATA_DIR}/.index/sqlite"
mkdir -p "${DATA_DIR}/.tmp"

# ── Step 3: Fix ownership on mounted volume ──────────────────────
if [ "$(id -u)" = "0" ]; then
    echo "[entrypoint] Fixing volume ownership..."
    # Volume root belongs to the app user (it must create the data tree
    # default_app/... and the integrations sentinel there); config files
    # are chowned back to the host user so they can edit
    # ~/.corti/corti.toml (file write permission suffices).
    chown -R app:app "${DATA_DIR}"
    chown "${HOST_UID}:${HOST_GID}" "${DATA_DIR}/corti.toml" "${DATA_DIR}/ome.toml" 2>/dev/null || true
    chown "${HOST_UID}:${HOST_GID}" "${MARKER}" 2>/dev/null || true
fi

# ── Step 4: Copy default config files if missing ─────────────────
if [ ! -f "${DATA_DIR}/corti.toml" ]; then
    echo "[entrypoint] Creating corti.toml from defaults..."
    cp /opt/corti/config/default.toml "${DATA_DIR}/corti.toml"
    chown "${HOST_UID}:${HOST_GID}" "${DATA_DIR}/corti.toml" 2>/dev/null || chown app:app "${DATA_DIR}/corti.toml"
fi

if [ ! -f "${DATA_DIR}/ome.toml" ]; then
    echo "[entrypoint] Creating ome.toml from defaults..."
    cp /opt/corti/config/default_ome.toml "${DATA_DIR}/ome.toml"
    chown "${HOST_UID}:${HOST_GID}" "${DATA_DIR}/ome.toml" 2>/dev/null || chown app:app "${DATA_DIR}/ome.toml"
fi

# ── Step 5: Validate external PG connectivity ────────────────────
: "${DB_HOST:?DB_HOST is required for slim mode — set via docker run -e DB_HOST=...}"
: "${DB_PORT:?DB_PORT is required}"
: "${DB_NAME:?DB_NAME is required}"
: "${DB_USER:?DB_USER is required}"
: "${DB_PASSWORD:?DB_PASSWORD is required}"

# ── Step 6: Launch corti ─────────────────────────────────────────
echo "[entrypoint] Starting corti server (slim, external PG at ${DB_HOST}:${DB_PORT}/${DB_NAME})..."
exec su -s /bin/bash app -c "exec /opt/corti/venv/bin/corti server start --host 0.0.0.0 --port 5473 --root '${DATA_DIR}' --log-level INFO"
