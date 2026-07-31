"""PG repo singleton for ``atomic_fact``."""

from __future__ import annotations

from corti.infra.persistence.pg.pg_repo import PgDailyLogRepoBase

from ..pg_manager import get_pool
from ..tables.atomic_fact import AtomicFact


class _AtomicFactRepo(PgDailyLogRepoBase):
    schema = AtomicFact

    async def _pool_lookup(self):
        return await get_pool()


atomic_fact_repo = _AtomicFactRepo()
