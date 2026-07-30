"""Repro: high-frequency atomic-replace bursts vs. cascade drain.

NOTE: Tests in this file depended on LanceDB modules which have been
removed from src/. All test functions, fixtures, and helpers have been
removed. Re-enable tests after migrating to the PostgreSQL-based cascade
pipeline.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from cortistrate.component.embedding import EmbeddingProvider
from cortistrate.component.tokenizer import build_tokenizer
from cortistrate.core.persistence import MarkdownReader, MemoryRoot
from cortistrate.memory.cascade import CascadeConfig, CascadeOrchestrator


class _StubEmbedder(EmbeddingProvider):
    dim = 1024

    async def embed(self, text: str) -> list[float]:
        return [0.0] * self.dim

    async def embed_batch(self, texts):  # type: ignore[no-untyped-def]
        return [[0.0] * self.dim for _ in texts]
