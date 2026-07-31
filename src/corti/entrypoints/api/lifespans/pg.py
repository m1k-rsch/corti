"""PG lifespan provider — initialises the async psycopg3 connection pool.

Replaces PostgresLifespanProvider and PGLiteLifespanProvider.
Connects to PostgreSQL 18.4 directly via psycopg_pool.AsyncConnectionPool.

Config is read from ``corti-pg.env``, env vars, or the ``[pg]`` section
of corti.toml.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from corti.core.lifespan import LifespanProvider
from corti.core.observability.logging import get_logger

logger = get_logger(__name__)


class PGLifespanProvider(LifespanProvider):
    """Manage the async PG connection pool for the app lifecycle.

    PG must be running and the database + pgvector extension must exist
    before the Corti server starts.
    """

    def __init__(self, order: int = 11) -> None:
        super().__init__(name="pg", order=order)

    async def startup(self, app: FastAPI) -> Any:
        from corti.infra.persistence.pg.pg_manager import init as pg_init

        pool = await pg_init(run_migrations=True)

        # Verify connectivity and extensions
        async with pool.connection() as conn:
            cur = await conn.execute("SELECT version()")
            version = (await cur.fetchone())["version"]
            cur = await conn.execute(
                "SELECT count(*) AS cnt FROM pg_extension WHERE extname = 'vector'"
            )
            ext_count = (await cur.fetchone())["cnt"]
            if ext_count == 0:
                raise RuntimeError("pgvector extension not available")
            cur = await conn.execute(
                "SELECT count(*) AS cnt FROM pg_tables WHERE schemaname = 'public'"
            )
            table_count = (await cur.fetchone())["cnt"]

        logger.info(
            "pg_ready",
            pg_version=version[:80] if version else "unknown",
            tables=table_count,
        )
        return pool

    async def shutdown(self, app: FastAPI) -> None:
        from corti.infra.persistence.pg.pg_manager import dispose as pg_dispose

        await pg_dispose()
