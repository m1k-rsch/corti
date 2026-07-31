"""Strict md <-> Postgres consistency across all 4 daily-log kinds.

NOTE: Tests in this file depended on LanceDB modules which have been
removed from src/. All test functions, fixtures, and helpers have been
removed. Re-enable tests after migrating to the PostgreSQL-based cascade
pipeline.
"""

from __future__ import annotations

from corti.component.embedding import EmbeddingProvider


class _StubEmbedder(EmbeddingProvider):
    dim = 1024

    async def embed(self, text: str) -> list[float]:
        return [0.0] * self.dim

    async def embed_batch(self, texts):  # type: ignore[no-untyped-def]
        return [[0.0] * self.dim for _ in texts]
