"""PG connection pool manager — process-wide singleton.

Wraps ``cortistrate.infra.persistence.pg.pool.create_pool`` to produce a
lazy, process-wide ``AsyncConnectionPool``. Lifespan providers call
``init()`` on startup and ``dispose()`` on shutdown. Repos call
``get_pool()`` on each request.

Usage::

    from cortistrate.infra.persistence.pg.pg_manager import init, dispose, get_pool

    # startup
    await init()

    # in a repo
    pool = await get_pool()
    async with pool.connection() as conn:
        ...

    # shutdown
    await dispose()
"""

from __future__ import annotations

import asyncio

from psycopg_pool import AsyncConnectionPool

from cortistrate.core.observability.logging import get_logger

from . import pool as _pool_mod
from .ddl import run_ddl

logger = get_logger(__name__)

_pool: AsyncConnectionPool | None = None
_lock = asyncio.Lock()


async def init(*, conninfo: str | None = None, run_migrations: bool = True) -> AsyncConnectionPool:
    """Initialize the singleton pool and optionally run DDL.

    Args:
        conninfo: psycopg connection string. If None, builds from env.
        run_migrations: If True, run ``run_ddl()`` to create tables & indexes.

    Returns:
        The initialized pool.
    """
    global _pool
    async with _lock:
        if _pool is not None:
            return _pool
        _pool = await _pool_mod.create_pool(conninfo)
        logger.info("pg_manager_initialized")

        if run_migrations:
            await run_ddl(_pool)
            logger.info("pg_ddl_executed")

        return _pool


async def dispose() -> None:
    """Close the singleton pool. Idempotent."""
    global _pool
    async with _lock:
        if _pool is not None:
            await _pool_mod.dispose_pool(_pool)
            _pool = None
            logger.info("pg_manager_disposed")


async def get_pool() -> AsyncConnectionPool:
    """Return the process-wide pool, initializing if needed."""
    if _pool is not None:
        return _pool
    return await init()


async def get_connection():
    """Return a connection context manager for one-shot queries.

    Preferred over ``get_pool().connection()`` for ad-hoc scripts.
    """
    pool = await get_pool()
    return pool.connection()
