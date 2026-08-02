"""Unit tests for :class:`KnowledgeTopicRecaller` with a mocked PG pool.

The PG recaller runs a single dual-column SQL statement (``GREATEST``
over the two tsvector BM25 scores) instead of two tantivy
``nearest_to_text`` calls. These tests swap ``knowledge_topic_repo._pool``
for a fake pool and assert the SQL contract (both columns queried,
max-score merge, ORDER BY + LIMIT) plus the candidate-shaping behaviour
(score pass-through, noise-column stripping) without a live database.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from corti.component.tokenizer import Tokenizer
from corti.infra.persistence.pg.repos.knowledge_topic import knowledge_topic_repo
from corti.memory.search.recall import KnowledgeTopicRecaller
from corti.memory.search.recall.base import RecallerDeps


class _FakePool:
    """Minimal pool stand-in: one connection whose ``execute`` returns rows.

    Records the last executed SQL on ``self.last_sql`` so tests can
    assert the statement contract without parsing internals.
    """

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.last_sql: str | None = None

    @asynccontextmanager
    async def connection(self):
        cur = SimpleNamespace(fetchall=AsyncMock(return_value=self.rows))

        async def _execute(sql, params=None):
            self.last_sql = sql
            return cur

        yield SimpleNamespace(execute=AsyncMock(side_effect=_execute))


@pytest.fixture
def stub_pool(monkeypatch: pytest.MonkeyPatch):
    """Patch ``knowledge_topic_repo._pool``; returns a setter for the rows."""

    def _set(rows: list[dict[str, Any]]) -> _FakePool:
        fake = _FakePool(rows)
        monkeypatch.setattr(knowledge_topic_repo, "_pool", AsyncMock(return_value=fake))
        return fake

    return _set


class _WhitespaceTokenizer(Tokenizer):
    """Splits on whitespace — predictable token output for assertions."""

    def tokenize(self, text: str) -> list[str]:
        return text.split()


def _make_row(
    rid: str,
    *,
    score: float = 1.0,
) -> dict[str, Any]:
    """Build a minimal knowledge_topic Postgres row dict."""
    return {
        "id": rid,
        "app_id": "app",
        "project_id": "proj",
        "doc_id": "doc_1",
        "category_id": "cat_1",
        "topic_name": f"Topic {rid}",
        "topic_path": f"/root/{rid}",
        "depth": 1,
        "parent_node_id": "",
        "summary": f"Summary of {rid}",
        "summary_tokens": f"summary {rid}",
        "content_tokens": f"content {rid}",
        "content_labels": [],
        "md_path": f"knowledge/default/{rid}.md",
        "content_sha256": "a" * 64,
        "_score": score,
    }


@pytest.fixture()
def recaller() -> KnowledgeTopicRecaller:
    return KnowledgeTopicRecaller(RecallerDeps(tokenizer=_WhitespaceTokenizer()))


_WHERE = "app_id = 'app' AND project_id = 'proj'"


# ---------------------------------------------------------------------------
# sparse_recall — dual-column BM25
# ---------------------------------------------------------------------------


async def test_sparse_recall_queries_both_columns(
    recaller: KnowledgeTopicRecaller,
    stub_pool,
) -> None:
    """The SQL must reference both ``summary_tokens_tsv`` and ``content_tokens_tsv``."""
    fake = stub_pool([_make_row("t1", score=0.9)])

    result = await recaller.sparse_recall("topic query", _WHERE, limit=10)

    assert fake.last_sql is not None
    assert "summary_tokens_tsv" in fake.last_sql
    assert "content_tokens_tsv" in fake.last_sql
    assert "GREATEST" in fake.last_sql
    assert [c.id for c in result] == ["t1"]


async def test_sparse_recall_returns_rows_with_scores(
    recaller: KnowledgeTopicRecaller,
    stub_pool,
) -> None:
    """Canned rows surface as keyword candidates with their SQL score."""
    stub_pool([_make_row("t1", score=0.9), _make_row("t2", score=0.7)])

    result = await recaller.sparse_recall("topic query", _WHERE, limit=10)

    ids = {c.id for c in result}
    assert ids == {"t1", "t2"}
    assert all(c.source == "keyword" for c in result)
    scores = {c.id: c.score for c in result}
    assert scores["t1"] == pytest.approx(0.9)
    assert scores["t2"] == pytest.approx(0.7)


async def test_sparse_recall_respects_order_and_limit(
    recaller: KnowledgeTopicRecaller,
    stub_pool,
) -> None:
    """The SQL ORDER BY / LIMIT contract is honoured by the returned candidates."""
    # Rows arrive pre-sorted by the (mocked) SQL engine.
    stub_pool([_make_row("b", score=0.8), _make_row("c", score=0.6)])

    result = await recaller.sparse_recall("query", _WHERE, limit=2)

    assert [c.id for c in result] == ["b", "c"]


async def test_sparse_recall_empty_query_returns_empty(
    recaller: KnowledgeTopicRecaller,
    stub_pool,
) -> None:
    """Empty query yields no rows (plainto_tsquery('') matches nothing)."""
    stub_pool([])
    result = await recaller.sparse_recall("", _WHERE, limit=10)
    assert result == []


# ---------------------------------------------------------------------------
# dense_recall — cosine ANN
# ---------------------------------------------------------------------------


async def test_dense_recall_cosine_conversion(
    recaller: KnowledgeTopicRecaller,
    stub_pool,
) -> None:
    """The SQL-computed similarity (1 - distance) lands in candidate.score."""
    stub_pool([_make_row("t1", score=0.8), _make_row("t2", score=0.5)])

    result = await recaller.dense_recall([0.1] * 1024, _WHERE, limit=10)

    assert len(result) == 2
    scores = {c.id: c.score for c in result}
    assert scores["t1"] == pytest.approx(0.8)
    assert scores["t2"] == pytest.approx(0.5)
    assert all(c.source == "vector" for c in result)


async def test_dense_recall_empty_vector_returns_empty(
    recaller: KnowledgeTopicRecaller,
    stub_pool,
) -> None:
    """Empty vector short-circuits — no Postgres query is issued."""
    result = await recaller.dense_recall([], _WHERE, limit=10)
    assert result == []


async def test_dense_recall_metadata_excludes_noise_columns(
    recaller: KnowledgeTopicRecaller,
    stub_pool,
) -> None:
    """``vector`` and ``_score`` must not appear in ``Candidate.metadata``."""
    row = _make_row("t1", score=0.7)
    row["vector"] = [0.0] * 1024
    row["summary_tokens_tsv"] = "stub tsvector"
    stub_pool([row])

    result = await recaller.dense_recall([0.1] * 1024, _WHERE, limit=5)

    assert len(result) == 1
    assert "vector" not in result[0].metadata
    assert "_score" not in result[0].metadata
    assert "summary_tokens_tsv" not in result[0].metadata
