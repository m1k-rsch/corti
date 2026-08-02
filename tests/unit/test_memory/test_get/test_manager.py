"""Unit tests for :class:`GetManager` with in-memory stub repos.

These tests exercise the dispatch / shape / sort-override logic without
Postgres. Each repo is replaced by a minimal stub that records the call
and returns canned rows; the manager's job is to:

* dispatch on ``memory_type`` to the matching repo,
* compile filters once and pass the same ``where`` to the repo,
* shape rows into the correct ``GetItem`` (lossless except score),
* fetch the owner's single profile row (KV-by-owner) and shape it into
  ``GetProfileItem``, or return ``[]`` on a cold-start miss.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any

import pytest

from corti.infra.persistence.pg import (
    AtomicFact,
    Episode,
    Foresight,
    UserProfile,
)
from corti.memory.get import (
    GetManager,
    GetMemoryType,
    GetRequest,
)
from corti.memory.search import FilterNode

# ── Stub repos ──────────────────────────────────────────────────────────


@dataclass
class _CallRecord:
    where: str = ""
    sort_by: str = ""
    descending: bool = True
    page: int = 0
    page_size: int = 0


@dataclass
class _StubRepo:
    """Records the call and returns ``(rows, total)`` verbatim."""

    rows: list[Any] = field(default_factory=list)
    total: int = 0
    last: _CallRecord = field(default_factory=_CallRecord)

    async def find_where_paginated(
        self,
        where: str,
        *,
        sort_by: str,
        descending: bool = True,
        page: int = 1,
        page_size: int = 20,
        max_fetch: int = 20000,
    ) -> tuple[list[Any], int]:
        self.last = _CallRecord(
            where=where,
            sort_by=sort_by,
            descending=descending,
            page=page,
            page_size=page_size,
        )
        return list(self.rows), self.total


@dataclass
class _ProfileStubRepo:
    """Stub ``user_profile_repo`` — returns its configured row by id."""

    row: Any = None
    last_id: str | None = None

    async def get_by_id(self, id_: str) -> Any:
        self.last_id = id_
        return self.row


# ── Fixtures ────────────────────────────────────────────────────────────


def _ts(day: int = 1) -> _dt.datetime:
    return _dt.datetime(2026, 1, day, tzinfo=_dt.UTC)


def _episode_row(entry: str) -> Episode:
    return Episode(
        id=f"u1_{entry}",
        entry_id=entry,
        owner_id="u1",
        owner_type="user",
        session_id="sess_a",
        timestamp=_ts(),
        parent_type="memcell",
        parent_id="mc_1",
        sender_ids=["u1", "assistant"],
        subject=f"subj {entry}",
        summary=f"summary {entry}",
        episode=f"body of {entry}",
        episode_tokens=f"body of {entry}",
        md_path=f"users/u1/episodes/{entry}.md",
        content_sha256="abc",
        vector=[0.0] * 1024,
    )


def _atomic_fact_row(entry: str) -> AtomicFact:
    return AtomicFact(
        id=f"u1_{entry}",
        entry_id=entry,
        owner_id="u1",
        owner_type="user",
        session_id="sess_a",
        timestamp=_ts(),
        parent_type="memcell",
        parent_id="mc_1",
        sender_ids=["u1"],
        fact=f"fact {entry}",
        fact_tokens=f"fact {entry}",
        md_path=f"users/u1/.atomic_facts/{entry}.md",
        content_sha256="abc",
        vector=[0.0] * 1024,
    )


def _foresight_row(entry: str) -> Foresight:
    return Foresight(
        id=f"u1_{entry}",
        entry_id=entry,
        owner_id="u1",
        owner_type="user",
        session_id="sess_a",
        timestamp=_ts(),
        parent_type="memcell",
        parent_id="mc_1",
        sender_ids=["u1"],
        foresight=f"foresight {entry}",
        foresight_tokens=f"foresight {entry}",
        md_path=f"users/u1/.foresights/{entry}.md",
        content_sha256="abc",
        vector=[0.0] * 1024,
    )


def _user_profile_row(owner: str = "u1") -> UserProfile:
    return UserProfile(
        id=owner,
        owner_id=owner,
        owner_type="user",
        app_id="default",
        project_id="default",
        summary=f"{owner} loves climbing in Yosemite",
        explicit_info_json='[{"category": "Hobby", "description": "climbing"}]',
        implicit_traits_json='[{"trait": "Outdoorsy"}]',
        profile_timestamp_ms=1780304400000,
        md_path=f"users/{owner}/user.md",
        content_sha256="abc",
    )


@pytest.fixture
def profile_repo() -> _ProfileStubRepo:
    return _ProfileStubRepo()


@pytest.fixture
def manager(
    profile_repo: _ProfileStubRepo,
) -> tuple[GetManager, _StubRepo, _StubRepo, _StubRepo]:
    ep = _StubRepo()
    af = _StubRepo()
    fr = _StubRepo()
    mgr = GetManager(
        episode_repo=ep,  # type: ignore[arg-type]
        atomic_fact_repo=af,  # type: ignore[arg-type]
        foresight_repo=fr,  # type: ignore[arg-type]
        user_profile_repo=profile_repo,  # type: ignore[arg-type]
    )
    return mgr, ep, af, fr


# ── Episode dispatch ────────────────────────────────────────────────────


async def test_episodic_memory_populates_episodes_and_counts(
    manager: tuple[GetManager, _StubRepo, _StubRepo, _StubRepo],
) -> None:
    mgr, ep, _, _ = manager
    ep.rows = [_episode_row("ep_1"), _episode_row("ep_2")]
    ep.total = 17  # filtered total may exceed the page
    req = GetRequest(
        user_id="u1",
        memory_type=GetMemoryType.EPISODE,
    )
    resp = await mgr.get(req)

    assert len(resp.request_id) == 32 and all(
        c in "0123456789abcdef" for c in resp.request_id
    )
    assert resp.data.total_count == 17
    assert resp.data.count == 2
    assert [item.id for item in resp.data.episodes] == ["u1_ep_1", "u1_ep_2"]
    assert resp.data.profiles == []
    assert resp.data.atomic_facts == []
    assert resp.data.foresights == []
    # The shaper maps the row's owner_id onto the item's user_id field.
    assert all(item.user_id == "u1" for item in resp.data.episodes)


async def test_episodic_memory_passes_where_and_sort_to_repo(
    manager: tuple[GetManager, _StubRepo, _StubRepo, _StubRepo],
) -> None:
    """The compiled ``where`` must include owner_id + filter clauses."""
    mgr, ep, _, _ = manager
    req = GetRequest(
        user_id="u1",
        memory_type=GetMemoryType.EPISODE,
        sort_by="timestamp",
        sort_order="asc",
        page=2,
        page_size=10,
        filters=FilterNode.model_validate({"session_id": "sess_a"}),
    )
    await mgr.get(req)
    assert "owner_id = 'u1'" in ep.last.where
    assert "owner_type = 'user'" in ep.last.where
    assert "session_id = 'sess_a'" in ep.last.where
    assert ep.last.sort_by == "timestamp"
    assert ep.last.descending is False  # asc
    assert ep.last.page == 2
    assert ep.last.page_size == 10


# ── Atomic-fact dispatch ────────────────────────────────────────────────


async def test_atomic_fact_memory_populates_facts(
    manager: tuple[GetManager, _StubRepo, _StubRepo, _StubRepo],
) -> None:
    mgr, _, af, _ = manager
    af.rows = [_atomic_fact_row("af_1"), _atomic_fact_row("af_2")]
    af.total = 2
    req = GetRequest(
        user_id="u1",
        memory_type=GetMemoryType.ATOMIC_FACT,
    )
    resp = await mgr.get(req)

    assert resp.data.total_count == 2
    assert resp.data.count == 2
    assert [item.id for item in resp.data.atomic_facts] == ["u1_af_1", "u1_af_2"]
    assert resp.data.episodes == []
    assert resp.data.foresights == []
    assert all(item.user_id == "u1" for item in resp.data.atomic_facts)


# ── Foresight dispatch ──────────────────────────────────────────────────


async def test_foresight_memory_populates_foresights(
    manager: tuple[GetManager, _StubRepo, _StubRepo, _StubRepo],
) -> None:
    mgr, _, _, fr = manager
    fr.rows = [_foresight_row("fs_1")]
    fr.total = 1
    req = GetRequest(
        user_id="u1",
        memory_type=GetMemoryType.FORESIGHT,
    )
    resp = await mgr.get(req)

    assert resp.data.total_count == 1
    assert resp.data.count == 1
    assert [item.id for item in resp.data.foresights] == ["u1_fs_1"]
    assert resp.data.episodes == []
    assert resp.data.atomic_facts == []


# ── Profile dispatch ────────────────────────────────────────────────────


async def test_profile_miss_returns_empty(
    manager: tuple[GetManager, _StubRepo, _StubRepo, _StubRepo],
) -> None:
    """Cold start (no profile row yet) → empty list + total_count=0."""
    mgr, ep, af, fr = manager  # profile_repo.row defaults to None
    req = GetRequest(
        user_id="u1",
        memory_type=GetMemoryType.PROFILE,
    )
    resp = await mgr.get(req)
    assert resp.data.profiles == []
    assert resp.data.total_count == 0
    assert resp.data.count == 0
    # The profile path never touches the paginated repos.
    assert ep.last.where == ""
    assert af.last.where == ""
    assert fr.last.where == ""


async def test_profile_hit_shapes_row_into_item(
    manager: tuple[GetManager, _StubRepo, _StubRepo, _StubRepo],
    profile_repo: _ProfileStubRepo,
) -> None:
    """A present profile row is fetched by owner and shaped + json-decoded."""
    mgr, *_ = manager
    profile_repo.row = _user_profile_row("u1")
    req = GetRequest(user_id="u1", memory_type=GetMemoryType.PROFILE)
    resp = await mgr.get(req)

    assert resp.data.total_count == 1
    assert resp.data.count == 1
    assert len(resp.data.profiles) == 1
    item = resp.data.profiles[0]
    assert item.id == "u1"
    assert item.user_id == "u1"
    # KV fetch keys on owner_id.
    assert profile_repo.last_id == "u1"
    # json buckets are decoded back into structured profile_data.
    assert item.profile_data["summary"] == "u1 loves climbing in Yosemite"
    assert item.profile_data["explicit_info"] == [
        {"category": "Hobby", "description": "climbing"}
    ]
    assert item.profile_data["implicit_traits"] == [{"trait": "Outdoorsy"}]
    assert item.profile_data["profile_timestamp_ms"] == 1780304400000
