"""PG repo singleton for ``knowledge_topic``."""

from __future__ import annotations

from corti.infra.persistence.pg.pg_repo import PgRepoBase

from ..pg_manager import get_pool
from ..tables.knowledge_topic import KnowledgeTopic


class _KnowledgeTopicRepo(PgRepoBase):
    schema = KnowledgeTopic

    async def _pool_lookup(self):
        return await get_pool()


knowledge_topic_repo = _KnowledgeTopicRepo()
