"""PG repo singleton for ``episode``."""

from __future__ import annotations

from cortistrate.infra.persistence.pg.pg_repo import PgDailyLogRepoBase

from ..pg_manager import get_pool
from ..tables.episode import Episode


class _EpisodeRepo(PgDailyLogRepoBase):
    schema = Episode

    async def _pool_lookup(self):
        return await get_pool()


episode_repo = _EpisodeRepo()
