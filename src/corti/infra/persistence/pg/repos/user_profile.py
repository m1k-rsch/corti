"""PG repo singleton for ``user_profile``."""

from __future__ import annotations

from corti.infra.persistence.pg.pg_repo import PgRepoBase

from ..pg_manager import get_pool
from ..tables.user_profile import UserProfile


class _UserProfileRepo(PgRepoBase):
    schema = UserProfile

    async def _pool_lookup(self):
        return await get_pool()


user_profile_repo = _UserProfileRepo()
