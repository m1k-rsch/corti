"""PG repo singleton for ``foresight``."""

from __future__ import annotations

from cortistrate.infra.persistence.pg.pg_repo import PgDailyLogRepoBase

from ..pg_manager import get_pool
from ..tables.foresight import Foresight


class _ForesightRepo(PgDailyLogRepoBase):
    schema = Foresight

    async def _pool_lookup(self):
        return await get_pool()


foresight_repo = _ForesightRepo()
