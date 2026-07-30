"""Public DTOs for ``POST /api/v1/memory/get``.

Contract per the final design (mirrors :mod:`memory.search.dto` shape,
minus ``score`` because /get is a paginated listing rather than a
ranked retrieval):

* ``owner_type`` × ``memory_type`` are strictly paired:

  - ``user`` → ``episode`` | ``profile``

* ``GetData`` always contains kind arrays for symmetry with
  ``/search``; only the requested kind is populated. ``total_count``
  is the predicate's true match count; ``count`` is the page size
  actually returned.

* ``filters`` reuses :class:`cortistrate.memory.search.FilterNode` —
  same DSL, same compile path, ``AND`` / ``OR`` combinators allowed.
  The earlier ``/get``-only ban on combinators (from wiki appendix C)
  was dropped: the legacy opensource memsys ``/get`` always supported
  combinators and there is no engine-side reason to forbid them.
"""

from __future__ import annotations

import datetime as _dt
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cortistrate.memory.search import FilterNode


class GetMemoryType(StrEnum):
    """The kinds enumerated by ``/get``.

    ``episode``, ``profile``, ``atomic_fact``, ``foresight`` are
    user-owned.
    """

    EPISODE = "episode"
    PROFILE = "profile"
    ATOMIC_FACT = "atomic_fact"
    FORESIGHT = "foresight"


# ── Request ──────────────────────────────────────────────────────────────


class GetRequest(BaseModel):
    """Request body for ``POST /api/v1/memory/get``.

    Callers identify the memory owner via ``user_id``.
    """

    model_config = ConfigDict(extra="forbid")

    user_id: str | None = Field(default=None, min_length=1)
    """Memory owner — provide ``user_id`` for ``episode`` / ``profile``."""
    app_id: str = "default"
    project_id: str = "default"
    """App / project scope (default ``\"default\"``). Pinned into the query
    ``where`` so a listing never crosses into another space's rows."""
    memory_type: GetMemoryType
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    sort_by: Literal["timestamp", "updated_at"] = "timestamp"
    """Sort column. ``profile`` silently overrides to ``updated_at``
    (profile has no timestamp)."""

    sort_order: Literal["asc", "desc"] = "desc"
    filters: FilterNode | None = None
    """Filters DSL — same shape as ``/search``, ``AND`` / ``OR``
    combinators allowed."""

    @property
    def owner_id(self) -> str:
        """Derived from ``user_id``."""
        return self.user_id or ""

    @property
    def owner_type(self) -> Literal["user", "agent"]:
        """``\"user\"`` always."""
        return "user"


# ── Item DTOs (mirror Search*Item shapes minus score) ────────────────────


class GetEpisodeItem(BaseModel):
    """Episode listing item — always user-scoped."""

    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str | None
    app_id: str = "default"
    project_id: str = "default"
    session_id: str
    timestamp: _dt.datetime
    sender_ids: list[str] = Field(default_factory=list)
    summary: str
    subject: str
    episode: str
    type: Literal["Conversation"]


class GetProfileItem(BaseModel):
    """Owner profile — at most one per response, only for user owners."""

    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str | None
    app_id: str = "default"
    project_id: str = "default"
    profile_data: dict[str, object]


class GetAtomicFactItem(BaseModel):
    """Atomic fact listing item — always user-scoped."""

    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str | None
    app_id: str = "default"
    project_id: str = "default"
    session_id: str | None = None
    parent_id: str | None = None
    content: str
    source: str | None = None
    timestamp: _dt.datetime


class GetForesightItem(BaseModel):
    """Foresight listing item — always user-scoped."""

    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str | None
    app_id: str = "default"
    project_id: str = "default"
    session_id: str | None = None
    content: str
    insight_type: str | None = None
    timestamp: _dt.datetime


# ── Response envelope ────────────────────────────────────────────────────


class GetData(BaseModel):
    """Body of ``response.data``.

    All arrays are always present so client code can iterate
    without branching on ``memory_type``; the route populates exactly
    one.
    """

    model_config = ConfigDict(extra="forbid")

    episodes: list[GetEpisodeItem] = Field(default_factory=list)
    profiles: list[GetProfileItem] = Field(default_factory=list)
    atomic_facts: list[GetAtomicFactItem] = Field(default_factory=list)
    foresights: list[GetForesightItem] = Field(default_factory=list)
    total_count: int = 0
    """Total rows matching the request's owner + filter predicate."""

    count: int = 0
    """Number of items in this page (``len(items)`` after slicing)."""


class GetResponse(BaseModel):
    """Top-level response envelope."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    data: GetData
