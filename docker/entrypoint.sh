#!/usr/bin/env bash
set -euo pipefail

# ── Cortistrate container entrypoint ──────────────────────────────
# Runs as root (the initial container process).  Performs:
#   1. chown the data volume for postgres and app users.
#   2. First-run PG initialization (initdb + user + database + extension).
#   3. Copy default config files if missing.
#   4. exec supervisord as PID 1.

DATA_DIR="${CORTISTRATE_ROOT:-/home/app/.cortistrate}"
PGDATA="${PGDATA:-${DATA_DIR}/.index/pg}"
PG_PORT="${DB_PORT:-5432}"
PG_USER="${DB_USER:-cortistrate}"
PG_DB="${DB_NAME:-cortistrate}"
PG_PASS="${DB_PASSWORD:-cortistrate_local_2026}"

# ── Step 1: Ensure required directories exist ────────────────────
mkdir -p "${DATA_DIR}/.index/sqlite"
mkdir -p "${DATA_DIR}/.tmp"
mkdir -p "${PGDATA}"

# ── Step 2: Fix ownership on mounted volume ──────────────────────
if [ "$(id -u)" = "0" ]; then
    echo "[entrypoint] Fixing volume ownership..."
    chown -R app:app "${DATA_DIR}"
    chown -R postgres:postgres "${PGDATA}"
fi

# ── Step 3: First-run PG initialization ────────────────────────────
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

    cat > "${PGDATA}/cortistrate.conf" << 'PGEOF'
listen_addresses = '127.0.0.1'
port = 5432
log_destination = 'stderr'
logging_collector = 'off'
unix_socket_directories = ''
PGEOF
    chown postgres:postgres "${PGDATA}/cortistrate.conf"

    echo "include = 'cortistrate.conf'" >> "${PGDATA}/postgresql.auto.conf"
    chown postgres:postgres "${PGDATA}/postgresql.auto.conf"
else
    echo "[entrypoint] Existing PG data found, skipping initialization."
fi

# ── Step 4: Copy default config files if missing ─────────────────
if [ ! -f "${DATA_DIR}/cortistrate.toml" ]; then
    echo "[entrypoint] Creating cortistrate.toml from defaults..."
    cp /opt/cortistrate/config/default.toml "${DATA_DIR}/cortistrate.toml"
    chown app:app "${DATA_DIR}/cortistrate.toml"
fi

if [ ! -f "${DATA_DIR}/ome.toml" ]; then
    echo "[entrypoint] Creating ome.toml from defaults..."
    cp /opt/cortistrate/config/default_ome.toml "${DATA_DIR}/ome.toml"
    chown app:app "${DATA_DIR}/ome.toml"
fi

# ── Step 5: Final ownership fix for any new files ─────────────────
if [ "$(id -u)" = "0" ]; then
    chown -R app:app "${DATA_DIR}"
    chown -R postgres:postgres "${PGDATA}"
fi

# ── Step 6: Launch supervisord ────────────────────────────────────
echo "[entrypoint] Starting supervisord (PG + cortistrate)..."
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
