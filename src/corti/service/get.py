"""Get use case — lazy singleton wiring for ``POST /api/v1/memory/get``.

``/get`` is read-only and uses no embedding / LLM / rerank clients —
it never blocks on optional components the way ``/search`` does.
"""

from __future__ import annotations

from corti.core.observability.logging import get_logger
from corti.infra.persistence.pg import (
    atomic_fact_repo,
    episode_repo,
    foresight_repo,
    user_profile_repo,
)
from corti.memory.get import GetManager, GetRequest, GetResponse

logger = get_logger(__name__)

_manager: GetManager | None = None


def _get_manager() -> GetManager:
    global _manager
    if _manager is None:
        _manager = GetManager(
            episode_repo=episode_repo,
            atomic_fact_repo=atomic_fact_repo,
            foresight_repo=foresight_repo,
            user_profile_repo=user_profile_repo,
        )
        logger.info("get_manager_built")
    return _manager


async def get(req: GetRequest) -> GetResponse:
    """Dispatch one /get request through the lazily-built manager."""
    return await _get_manager().get(req)
