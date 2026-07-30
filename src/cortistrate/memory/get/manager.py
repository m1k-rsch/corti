"""GetManager — top-level orchestrator for ``POST /api/v1/memory/get``.

Hard partition by ``(owner_type, memory_type)`` (validated by
:class:`GetRequest`):

* ``user`` + ``episode``       → ``data.episodes``
* ``user`` + ``profile``       → ``data.profiles`` (one-row KV fetch
  from the ``user_profile`` table; at most one item)
* ``user`` + ``atomic_fact``   → ``data.atomic_facts``
* ``user`` + ``foresight``     → ``data.foresights``

Reads only — never writes. Filters are compiled through
:func:`compile_filters_for_get` so the column allow-list stays
shared with :mod:`memory.search`. Pagination + in-memory sort
runs through :meth:`DbRepoBase.find_where_paginated`.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from cortistrate.component.utils.datetime import to_display_tz
from cortistrate.core.observability.logging import get_logger
from cortistrate.core.observability.tracing import gen_request_id

from .dto import (
    GetAtomicFactItem,
    GetData,
    GetEpisodeItem,
    GetForesightItem,
    GetMemoryType,
    GetProfileItem,
    GetRequest,
    GetResponse,
)
from .filters_adapter import compile_filters_for_get

if TYPE_CHECKING:
    from cortistrate.infra.persistence.pg import (
        AtomicFact,
        Episode,
        Foresight,
        UserProfile,
    )
    from cortistrate.infra.persistence.pg.pg_repo import PgRepoBase as DbRepoBase

logger = get_logger(__name__)


class GetManager:
    """Dispatch ``GetRequest`` to the matching DB-backed repo and
    shape rows into the public DTO."""

    def __init__(
        self,
        *,
        episode_repo: DbRepoBase[Episode],
        atomic_fact_repo: DbRepoBase[AtomicFact],
        foresight_repo: DbRepoBase[Foresight],
        user_profile_repo: DbRepoBase[UserProfile],
    ) -> None:
        self._ep = episode_repo
        self._fact = atomic_fact_repo
        self._fore = foresight_repo
        self._profile = user_profile_repo

    # ── Public entry ─────────────────────────────────────────────────

    async def get(self, req: GetRequest) -> GetResponse:
        request_id = gen_request_id()
        descending = req.sort_order == "desc"
        where = compile_filters_for_get(
            req.filters,
            owner_id=req.owner_id,
            owner_type=req.owner_type,
            app_id=req.app_id,
            project_id=req.project_id,
        )

        match req.memory_type:
            case GetMemoryType.EPISODE:
                rows, total = await self._ep.find_where_paginated(
                    where,
                    sort_by=req.sort_by,
                    descending=descending,
                    page=req.page,
                    page_size=req.page_size,
                )
                items = [self._shape_episode(r) for r in rows]
                data = GetData(
                    episodes=items,
                    total_count=total,
                    count=len(items),
                )
            case GetMemoryType.PROFILE:
                profiles = await self._fetch_profile(req.owner_id)
                data = GetData(
                    profiles=profiles,
                    total_count=len(profiles),
                    count=len(profiles),
                )
            case GetMemoryType.ATOMIC_FACT:
                rows, total = await self._fact.find_where_paginated(
                    where,
                    sort_by=req.sort_by,
                    descending=descending,
                    page=req.page,
                    page_size=req.page_size,
                )
                items = [self._shape_atomic_fact(r) for r in rows]
                data = GetData(
                    atomic_facts=items,
                    total_count=total,
                    count=len(items),
                )
            case GetMemoryType.FORESIGHT:
                rows, total = await self._fore.find_where_paginated(
                    where,
                    sort_by=req.sort_by,
                    descending=descending,
                    page=req.page,
                    page_size=req.page_size,
                )
                items = [self._shape_foresight(r) for r in rows]
                data = GetData(
                    foresights=items,
                    total_count=total,
                    count=len(items),
                )

        return GetResponse(request_id=request_id, data=data)

    # ── Shapers ──────────────────────────────────────────────────────

    @staticmethod
    def _shape_episode(row: Episode) -> GetEpisodeItem:
        return GetEpisodeItem(
            id=row.id,
            user_id=row.owner_id,
            app_id=row.app_id,
            project_id=row.project_id,
            session_id=row.session_id,
            timestamp=to_display_tz(row.timestamp),
            sender_ids=row.sender_ids,
            summary=row.summary or "",
            subject=row.subject or "",
            episode=row.episode,
            type="Conversation",
        )

    @staticmethod
    def _shape_atomic_fact(row: AtomicFact) -> GetAtomicFactItem:
        return GetAtomicFactItem(
            id=row.id,
            user_id=row.owner_id,
            app_id=row.app_id,
            project_id=row.project_id,
            session_id=row.session_id,
            parent_id=row.parent_id,
            content=row.fact,
            source=row.source if hasattr(row, "source") else None,
            timestamp=to_display_tz(row.timestamp),
        )

    @staticmethod
    def _shape_foresight(row: Foresight) -> GetForesightItem:
        return GetForesightItem(
            id=row.id,
            user_id=row.owner_id,
            app_id=row.app_id,
            project_id=row.project_id,
            session_id=row.session_id,
            content=row.foresight if hasattr(row, "foresight") else "",
            insight_type=None,
            timestamp=to_display_tz(row.timestamp),
        )

    # ── Profile ──────────────────────────────────────────────────────

    async def _fetch_profile(self, owner_id: str) -> list[GetProfileItem]:
        if not owner_id:
            return []
        row = await self._profile.get_by_id(owner_id)
        if row is None:
            logger.debug("get_profile_miss", owner_id=owner_id)
            return []
        profile_data: dict[str, object] = {
            "summary": row.summary,
            "explicit_info": _load_json(row.explicit_info_json),
            "implicit_traits": _load_json(row.implicit_traits_json),
            "profile_timestamp_ms": row.profile_timestamp_ms,
        }
        return [
            GetProfileItem(
                id=row.id,
                user_id=row.owner_id,
                app_id=row.app_id,
                project_id=row.project_id,
                profile_data=profile_data,
            )
        ]


def _load_json(text: str) -> Any:
    if not text:
        return []
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.debug("get_profile_json_decode_failed", payload_head=text[:80])
        return []
