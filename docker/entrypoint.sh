#!/usr/bin/env bash
set -euo pipefail

# ── Corti container entrypoint ──────────────────────────────
# Runs as root (the initial container process).  Performs:
#   1. Resolve the host user (uid/gid) that owns the mounted volume.
#   2. chown the data volume for postgres and app users.
#   3. First-run PG initialization (initdb + user + database + extension).
#   4. Copy default config files if missing.
#   5. Final ownership — volume root to app, configs to host.
#   6. exec supervisord as PID 1.

DATA_DIR="${CORTI_ROOT:-/home/app/.corti}"
PGDATA="${PGDATA:-${DATA_DIR}/.index/pg}"
PG_PORT="${DB_PORT:-5432}"
PG_USER="${DB_USER:-corti}"
PG_DB="${DB_NAME:-corti}"
PG_PASS="${DB_PASSWORD:-corti_local_2026}"

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
mkdir -p "${PGDATA}"

# ── Step 3: Fix ownership on mounted volume ──────────────────────
if [ "$(id -u)" = "0" ]; then
    echo "[entrypoint] Fixing volume ownership..."
    # Only chown data subdirectories — never the config files at the root
    # (~/.corti/corti.toml, ome.toml). Those must stay owned by the host
    # user so they can edit them (README: "edit ~/.corti/corti.toml →
    # docker restart"). Chowning the whole volume breaks that workflow.
    chown -R app:app "${DATA_DIR}/.index" "${DATA_DIR}/.tmp" 2>/dev/null || true
    chown -R postgres:postgres "${PGDATA}"
fi

# ── Step 4: First-run PG initialization ────────────────────────────
if [ ! -f "${PGDATA}/PG_VERSION" ]; then
    echo "[entrypoint] First run: initializing PostgreSQL data cluster..."

    # Initialize with trust auth — we replace pg_hba.conf after bootstrap.
    su -s /bin/bash postgres -c "
        /usr/lib/postgresql/18/bin/initdb \
            -D '${PGDATA}' \
            --auth=trust \
            --no-locale \
            --encoding=UTF8
    "

    # Start PG temporarily with default config (Unix socket + TCP available).
    echo "[entrypoint] Starting PG temporarily for bootstrap..."
    su -s /bin/bash postgres -c "
        /usr/lib/postgresql/18/bin/pg_ctl start \
            -D '${PGDATA}' \
            -l '${PGDATA}/init.log' \
            -w --timeout=60
    "

    # Create user, database, and enable pgvector via Unix socket (peer auth).
    echo "[entrypoint] Creating database user and enabling pgvector..."
    su -s /bin/bash postgres -c "psql -d postgres" <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '${PG_USER}') THEN
        CREATE ROLE ${PG_USER} WITH LOGIN PASSWORD '${PG_PASS}';
    ELSE
        ALTER ROLE ${PG_USER} WITH PASSWORD '${PG_PASS}';
    END IF;
END
\$\$;

SELECT 'CREATE DATABASE ${PG_DB} OWNER ${PG_USER}'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${PG_DB}')
\gexec

\c ${PG_DB}
CREATE EXTENSION IF NOT EXISTS vector;
SQL

    # Stop PG — we restart it via supervisord with the production configs.
    echo "[entrypoint] Bootstrap complete. Stopping PG..."
    su -s /bin/bash postgres -c "
        /usr/lib/postgresql/18/bin/pg_ctl stop \
            -D '${PGDATA}' -m fast
    "
    rm -f "${PGDATA}/init.log"

    # Now write production configs: TCP only, password auth.
    # These take effect when supervisord starts PG.

    cat > "${PGDATA}/pg_hba.conf" << 'HBAEOF'
# TYPE  DATABASE  USER      ADDRESS       METHOD
local   all       postgres                peer
local   all       all                     peer
host    all       all       127.0.0.1/32  md5
host    all       all       ::1/128       md5
HBAEOF
    chown postgres:postgres "${PGDATA}/pg_hba.conf"

    cat > "${PGDATA}/corti.conf" << 'PGEOF'
listen_addresses = '127.0.0.1'
port = 5432
log_destination = 'stderr'
logging_collector = 'off'
unix_socket_directories = ''
PGEOF
    chown postgres:postgres "${PGDATA}/corti.conf"

    echo "include = 'corti.conf'" >> "${PGDATA}/postgresql.auto.conf"
    chown postgres:postgres "${PGDATA}/postgresql.auto.conf"
else
    echo "[entrypoint] Existing PG data found, skipping initialization."
fi

# ── Step 5: Copy default config files if missing ─────────────────
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

# ── Step 6: Final ownership — volume root to app, configs to host ──
# The app process must be able to create the data tree (default_app/,
# arbitrary app/project dirs) and the integrations sentinel at the
# volume root, so the root itself belongs to the app user. The config
# files (corti.toml / ome.toml) are chowned back to the HOST user —
# editing a file only needs file write permission, not directory write
# permission, so the documented "edit corti.toml → docker restart" keeps
# working on every boot (F13 fix: the host user comes from the
# .host-user marker / config-file probe, never from the volume root,
# which this step chowns to the app user).
if [ "$(id -u)" = "0" ]; then
    chown -R app:app "${DATA_DIR}"
    chown "${HOST_UID}:${HOST_GID}" "${DATA_DIR}/corti.toml" "${DATA_DIR}/ome.toml" 2>/dev/null || true
    chown "${HOST_UID}:${HOST_GID}" "${MARKER}" 2>/dev/null || true
    chown -R postgres:postgres "${PGDATA}"
fi

# ── Step 7: Launch supervisord ────────────────────────────────────
echo "[entrypoint] Starting supervisord (PG + corti)..."
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
