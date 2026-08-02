"""Unit tests for :class:`EpisodeRecaller` with a mocked PG pool.

The PG recallers talk to Postgres through ``episode_repo._pool()``
(psycopg async pool) and raw SQL — there is no ``get_table``/tantivy
surface anymore. These tests swap the repo's pool lookup for a fake
pool whose connection returns canned ``dict`` rows, exercising the
candidate-shaping logic (entry_id keying, parent_id injection, noise
column stripping) without a live database.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from corti.component.tokenizer import Tokenizer
from corti.infra.persistence.pg.repos.episode import episode_repo
from corti.memory.search.recall import EpisodeRecaller
from corti.memory.search.recall.base import RecallerDeps


class _FakePool:
    """Minimal pool stand-in: one connection whose ``execute`` returns rows."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    @asynccontextmanager
    async def connection(self):
        cur = SimpleNamespace(fetchall=AsyncMock(return_value=self.rows))
        yield SimpleNamespace(execute=AsyncMock(return_value=cur))


@pytest.fixture
def stub_pool(monkeypatch: pytest.MonkeyPatch):
    """Patch ``episode_repo._pool``; returns a setter for the canned rows."""

    def _set(rows: list[dict[str, Any]]) -> None:
        monkeypatch.setattr(
            episode_repo, "_pool", AsyncMock(return_value=_FakePool(rows))
        )

    return _set


def _make_row(
    ep_id: str,
    mc_id: str,
    *,
    parent_type: str = "memcell",
    entry_id: str = "",
    score: float | None = None,
) -> dict[str, Any]:
    """Build a minimal episode Postgres row dict for test fixtures."""
    row: dict[str, Any] = {
        "id": ep_id,
        "owner_id": "alice",
        "owner_type": "user",
        "session_id": "sess_1",
        "timestamp": 1000000,
        "sender_ids": ["alice"],
        "subject": f"subj {ep_id}",
        "summary": f"summary {ep_id}",
        "episode": f"body {ep_id}",
        "parent_id": mc_id,
        "parent_type": parent_type,
        "entry_id": entry_id or ep_id,
    }
    if score is not None:
        row["_score"] = score
    return row


@pytest.fixture()
def recaller() -> EpisodeRecaller:
    tok = AsyncMock(spec=Tokenizer)
    tok.tokenize.return_value = ["hi"]
    return EpisodeRecaller(RecallerDeps(tokenizer=tok))


async def test_fetch_all_for_owner_returns_entry_id_keyed_candidates(
    recaller: EpisodeRecaller,
    stub_pool,
) -> None:
    """id must equal entry_id so acluster_retrieve membership works."""
    stub_pool([_make_row("ep_1", "mc_1"), _make_row("ep_2", "mc_2")])

    result = await recaller.fetch_all_for_owner("owner_id = 'alice'")

    assert len(result) == 2
    ids = {c.id for c in result}
    assert ids == {"ep_1", "ep_2"}, "id must be entry_id"


async def test_fetch_all_for_owner_stores_episode_id_in_metadata(
    recaller: EpisodeRecaller,
    stub_pool,
) -> None:
    """metadata['episode_id'] carries the real Postgres episode id for final shaping."""
    stub_pool([_make_row("ep_abc", "mc_xyz")])

    result = await recaller.fetch_all_for_owner("owner_id = 'alice'")

    assert result[0].metadata["episode_id"] == "ep_abc"
    assert result[0].metadata["parent_id"] == "mc_xyz"


async def test_fetch_all_for_owner_skips_rows_without_entry_id(
    recaller: EpisodeRecaller,
    stub_pool,
) -> None:
    """Rows without entry_id are silently skipped."""
    stub_pool(
        [
            {
                "id": "ep_bad",
                "owner_id": "alice",
                "owner_type": "user",
                "session_id": "s",
                "timestamp": 1,
                "sender_ids": [],
                "subject": "",
                "summary": "",
                "episode": "",
                "parent_id": "mc_x",
            },
        ]
    )

    result = await recaller.fetch_all_for_owner("owner_id = 'alice'")

    assert result == []


async def test_fetch_all_for_owner_merged_episode_uses_entry_id(
    recaller: EpisodeRecaller,
    stub_pool,
) -> None:
    """Merged episodes (parent_type=cluster) must use entry_id as Candidate.id."""
    stub_pool(
        [
            _make_row(
                "ep_merged", "cluster_abc", parent_type="cluster", entry_id="entry_xyz"
            )
        ]
    )

    result = await recaller.fetch_all_for_owner("owner_id = 'alice'")

    assert len(result) == 1
    assert result[0].id == "entry_xyz", "merged episode id must be entry_id"
    assert result[0].metadata["episode_id"] == "ep_merged"


async def test_fetch_all_for_owner_mixed_regular_and_merged(
    recaller: EpisodeRecaller,
    stub_pool,
) -> None:
    """Mixed rows: both regular and merged episodes key by entry_id."""
    stub_pool(
        [
            _make_row("ep_regular", "mc_1"),
            _make_row(
                "ep_merged", "cluster_99", parent_type="cluster", entry_id="entry_42"
            ),
        ]
    )

    result = await recaller.fetch_all_for_owner("owner_id = 'alice'")

    assert len(result) == 2
    ids = {c.id for c in result}
    assert ids == {"ep_regular", "entry_42"}


async def test_fetch_by_entry_ids_returns_candidates(
    recaller: EpisodeRecaller,
    stub_pool,
) -> None:
    """fetch_by_entry_ids returns candidates keyed by the row id."""
    stub_pool(
        [
            _make_row(
                "ep_merged", "cluster_abc", parent_type="cluster", entry_id="entry_xyz"
            )
        ]
    )

    result = await recaller.fetch_by_entry_ids(["entry_xyz"], "owner_id = 'alice'")

    assert len(result) == 1
    assert result[0].id == "ep_merged"


async def test_fetch_by_entry_ids_empty_input_returns_empty(
    recaller: EpisodeRecaller,
    stub_pool,
) -> None:
    """Empty entry_ids list short-circuits without querying."""
    result = await recaller.fetch_by_entry_ids([], "owner_id = 'alice'")
    assert result == []


async def test_sparse_recall_as_child_injects_parent_id(
    recaller: EpisodeRecaller,
    stub_pool,
) -> None:
    """sparse_recall_as_child adds parent_id=entry_id to each candidate's metadata."""
    stub_pool([_make_row("ep_1", "mc_1", entry_id="entry_1", score=1.0)])

    result = await recaller.sparse_recall_as_child(
        "hello", "owner_id = 'alice'", limit=10
    )

    assert len(result) == 1
    assert result[0].metadata["parent_id"] == "entry_1"


async def test_sparse_recall_as_child_falls_back_to_id_when_no_entry_id(
    recaller: EpisodeRecaller,
    stub_pool,
) -> None:
    """When entry_id is absent in metadata, parent_id falls back to candidate id."""
    row = {
        "id": "ep_2",
        "owner_id": "alice",
        "owner_type": "user",
        "session_id": "s",
        "timestamp": 1,
        "sender_ids": [],
        "subject": "",
        "summary": "",
        "episode": "body",
        "parent_id": "mc_x",
        "_score": 0.5,
    }
    stub_pool([row])

    result = await recaller.sparse_recall_as_child(
        "hello", "owner_id = 'alice'", limit=10
    )

    assert len(result) == 1
    cand = result[0]
    assert cand.metadata["parent_id"] == cand.id


async def test_sparse_recall_as_child_empty_query_returns_empty(
    recaller: EpisodeRecaller,
    stub_pool,
) -> None:
    """Empty query yields no rows (plainto_tsquery('') matches nothing)."""
    stub_pool([])
    result = await recaller.sparse_recall_as_child("", "owner_id = 'alice'", limit=10)
    assert result == []


async def test_dense_recall_as_child_injects_parent_id(
    recaller: EpisodeRecaller,
    stub_pool,
) -> None:
    """dense_recall_as_child adds parent_id=entry_id to each candidate's metadata."""
    stub_pool([_make_row("ep_3", "mc_3", entry_id="entry_3", score=0.9)])

    result = await recaller.dense_recall_as_child(
        [0.1] * 1024, "owner_id = 'alice'", limit=10
    )

    assert len(result) == 1
    assert result[0].metadata["parent_id"] == "entry_3"


async def test_dense_recall_as_child_empty_vector_returns_empty(
    recaller: EpisodeRecaller,
    stub_pool,
) -> None:
    """Empty vector short-circuits without querying."""
    result = await recaller.dense_recall_as_child([], "owner_id = 'alice'", limit=10)
    assert result == []


async def test_dense_recall_subject_returns_subject_vector_source(
    recaller: EpisodeRecaller,
    stub_pool,
) -> None:
    """dense_recall_subject returns source='vector' with the SQL-computed score."""
    stub_pool([_make_row("ep_s1", "mc_s1", entry_id="entry_s1", score=0.8)])

    result = await recaller.dense_recall_subject(
        [0.1] * 1024, "owner_id = 'alice'", limit=10
    )

    assert len(result) == 1
    assert result[0].source == "vector"
    assert result[0].score == pytest.approx(0.8)


async def test_dense_recall_subject_empty_vector_returns_empty(
    recaller: EpisodeRecaller,
    stub_pool,
) -> None:
    """Empty vector short-circuits without querying."""
    result = await recaller.dense_recall_subject([], "owner_id = 'alice'", limit=10)
    assert result == []


async def test_dense_recall_subject_as_child_injects_parent_id(
    recaller: EpisodeRecaller,
    stub_pool,
) -> None:
    """dense_recall_subject_as_child adds parent_id=entry_id to metadata."""
    stub_pool([_make_row("ep_s2", "mc_s2", entry_id="entry_s2", score=0.85)])

    result = await recaller.dense_recall_subject_as_child(
        [0.1] * 1024, "owner_id = 'alice'", limit=10
    )

    assert len(result) == 1
    assert result[0].metadata["parent_id"] == "entry_s2"
    assert result[0].source == "vector"


async def test_dense_recall_subject_as_child_empty_vector_returns_empty(
    recaller: EpisodeRecaller,
    stub_pool,
) -> None:
    """Empty vector short-circuits without querying."""
    result = await recaller.dense_recall_subject_as_child(
        [], "owner_id = 'alice'", limit=10
    )
    assert result == []
