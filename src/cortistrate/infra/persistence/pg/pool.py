"""Async psycopg3 connection pool for PostgreSQL 18.4.

Uses ``psycopg_pool.AsyncConnectionPool``. Connections are fully async
(no ``asyncio.to_thread`` wrapper — unlike PGLite's single-threaded WASM).

Pool settings are read from ``cortistrate-pg.env`` or environment variables:
    - DB_HOST (default: localhost)
    - DB_PORT (default: 5432)
    - DB_NAME (default: cortistrate)
    - DB_USER (default: cortistrate)
    - DB_PASSWORD (default: cortistrate_local_2026)

The pool is a process-wide singleton managed by ``pg_manager.py``.
"""

from __future__ import annotations

import os
from pathlib import Path

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from cortistrate.core.observability.logging import get_logger

logger = get_logger(__name__)

# ── Default connection info ────────────────────────────────────────────────

_DEFAULTS = {
    "host": "localhost",
    "port": 5432,
    "dbname": "cortistrate",
    "user": "cortistrate",
    "password": "cortistrate_local_2026",
}


def _load_env() -> dict[str, str | int]:
    """Load PG connection params from cortistrate-pg.env, falling back to env vars.

    Resolution order (first wins):
        1. ``cortistrate-pg.env`` in project root (absolute path)
        2. ``CORTISTRATE_PG_ENV`` env var pointing to a .env file
        3. ``DB_HOST`` / ``DB_PORT`` / etc. environment variables
        4. Built-in defaults
    """
    params: dict[str, str | int] = {}

    # Try cortistrate-pg.env from known location
    env_file = os.environ.get("CORTISTRATE_PG_ENV", "")
    if not env_file:
        candidates = [
            Path("/home/u1/.cortistrate/pg.env"),
        ]
        for c in candidates:
            if c.exists():
                env_file = str(c)
                break

    if env_file and os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                params[key] = val

    # Environment variable overrides (and fallback)
    for pg_key, env_key in [
        ("host", "DB_HOST"),
        ("port", "DB_PORT"),
        ("dbname", "DB_NAME"),
        ("user", "DB_USER"),
        ("password", "DB_PASSWORD"),
    ]:
        if env_key in os.environ:
            params[pg_key] = os.environ[env_key]
        elif pg_key not in params:
            params[pg_key] = _DEFAULTS[pg_key]

    if isinstance(params.get("port"), str):
        params["port"] = int(params["port"])

    return params


def build_conninfo(params: dict[str, str | int] | None = None) -> str:
    """Build a psycopg connection string from params dict.

    Returns a space-separated ``key=value`` string (psycopg3's native format).
    """
    if params is None:
        params = _load_env()
    parts = [f"host={params['host']}",
             f"port={params['port']}",
             f"dbname={params['dbname']}",
             f"user={params['user']}",
             f"password={params['password']}"]
    return " ".join(parts)


async def create_pool(
    conninfo: str | None = None,
    *,
    min_size: int = 2,
    max_size: int = 10,
) -> AsyncConnectionPool:
    """Create and open a new async connection pool.

    Args:
        conninfo: psycopg connection string. If None, builds from env.
        min_size: Minimum number of idle connections to keep.
        max_size: Maximum pool size.
    """
    if conninfo is None:
        conninfo = build_conninfo()

    pool = AsyncConnectionPool(
        conninfo=conninfo,
        min_size=min_size,
        max_size=max_size,
        open=False,
        kwargs={
            "options": "-c statement_timeout=30000",
            "row_factory": dict_row,
        },
    )
    await pool.open()
    logger.info("pg_pool_opened", host=str(_DEFAULTS["host"]), port=str(_DEFAULTS["port"]))
    return pool


async def dispose_pool(pool: AsyncConnectionPool) -> None:
    """Close the pool and release all connections."""
    await pool.close()
    logger.info("pg_pool_closed")
