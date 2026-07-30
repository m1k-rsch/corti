"""End-to-end cascade flow.

Drives the full pipeline once with real components except the embedder
(stubbed so the test never Hits an external API):

    EpisodeWriter.append_entry   ─▶  md file on disk
    watchdog FSEvents thread     ─▶  CascadeWatcher._enqueue_async
    md_change_state.upsert        ─▶  pending row
    CascadeWorker.drain_once     ─▶  EpisodeHandler.handle_added_or_modified
    episode_repo.upsert          ─▶  Postgres row

Asserts the row landed with the right shape (md_path, content_sha256,
episode tokens, vector dim). Validates that the three loops actually
talk to each other — no unit test covers the cross-loop wiring.

NOTE: Tests in this file depended on LanceDB modules which have been
removed from src/. All test functions and the cascade_runtime fixture
have been removed. The stub helpers remain as reference; re-enable
tests after migrating to the PostgreSQL-based cascade pipeline.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from cortistrate.component.embedding import EmbeddingProvider
from cortistrate.core.persistence import MemoryRoot


class _StubEmbedder(EmbeddingProvider):
    """1024-dim deterministic vector; counts calls for the assertion."""

    dim = 1024

    def __init__(self) -> None:
        self.calls = 0

    async def embed(self, text: str) -> list[float]:
        self.calls += 1
        return [0.0] * self.dim

    async def embed_batch(self, texts):  # type: ignore[no-untyped-def]
        return [await self.embed(t) for t in texts]


async def _poll(condition, *, deadline_seconds: float = 10.0, interval: float = 0.05):  # type: ignore[no-untyped-def]
    """Poll ``condition()`` (async) until truthy, or :class:`TimeoutError`.

    Wraps the loop in :func:`asyncio.timeout` so the test surfaces a
    clean ``TimeoutError`` instead of silently spinning. The polling
    interval is a low-cost sleep; the deadline is the hard cap.
    """
    async with asyncio.timeout(deadline_seconds):
        while True:
            result = await condition()
            if result:
                return result
            await asyncio.sleep(interval)
