"""Shared fixtures for ``memory.search`` unit tests.

The recall tests under this directory split into two families:

* **mock-based** (``test_recall_episode`` / ``test_recall_knowledge_topic``)
  — patch the repo pool, never touch a database;
* **real-Postgres** (``test_recall_atomic_fact`` / ``test_recall_or_semantics``
  / ``test_recall_profile``) — exercise the psycopg query path against a
  live PostgreSQL.

The real-Postgres tests need an **isolated** ``corti_test`` database.
The shared ``corti`` database is off-limits: integration/search tests
persist their session corpus there and a TRUNCATE would silently destroy
it. ``corti_test`` is created once by an operator (``sudo -u postgres
psql -c "CREATE DATABASE corti_test OWNER corti;"``); the session
fixture probes it and **skips** the PG tests when it is unavailable, so
a machine without the test DB (or without Postgres at all) still gets a
green suite.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

_TEST_DB = "corti_test"


def _pg_test_db_reachable() -> bool:
    """Probe ``corti_test`` using the same env resolution as ``pool.py``."""
    try:
        import psycopg

        from corti.infra.persistence.pg.pool import _load_env, build_conninfo
    except Exception:
        return False
    params = _load_env()
    params["dbname"] = _TEST_DB
    try:
        with psycopg.connect(build_conninfo(params), connect_timeout=3):
            return True
    except Exception:
        return False


@pytest_asyncio.fixture(scope="session")
async def pg_runtime() -> AsyncIterator[None]:
    """Point the process-wide PG pool at ``corti_test`` and run DDL once.

    Skipped (with all dependants) when the test DB is not reachable —
    real-Postgres tests are optional, not required.
    """
    if not _pg_test_db_reachable():
        pytest.skip(
            "corti_test database not available — real-Postgres recall tests skipped"
        )

    old_db = os.environ.get("DB_NAME")
    os.environ["DB_NAME"] = _TEST_DB

    from corti.infra.persistence.pg import dispose, init

    await init(run_migrations=True)
    try:
        yield
    finally:
        await dispose()
        if old_db is None:
            os.environ.pop("DB_NAME", None)
        else:
            os.environ["DB_NAME"] = old_db


@pytest_asyncio.fixture
async def pg_clean_tables(pg_runtime: None) -> AsyncIterator[None]:
    """TRUNCATE the five PG tables before each real-PG test.

    Each test seeds its own tiny corpus; truncating up front keeps
    assertions independent of test order.
    """
    from corti.infra.persistence.pg import get_pool

    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            "TRUNCATE episode, atomic_fact, foresight, knowledge_topic, "
            "user_profile RESTART IDENTITY CASCADE"
        )
        await conn.commit()
    yield
