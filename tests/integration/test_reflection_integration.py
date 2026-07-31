"""End-to-end Reflection INIT cycle integration test.

NOTE: Tests in this file depended on LanceDB modules which have been
removed from src/. All test functions, fixtures, and helpers have been
removed. Re-enable tests after migrating to the PostgreSQL-based
reflection pipeline.
"""

from __future__ import annotations

import hashlib

import numpy as np


class _StubEmbedder:
    """Return deterministic 1024-dim vectors seeded by input text."""

    dim: int = 1024

    async def embed(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        seed = int.from_bytes(digest[:8], "little")
        rng = np.random.default_rng(seed)
        vec = rng.standard_normal(self.dim).astype(np.float32)
        norm = float(np.linalg.norm(vec)) or 1.0
        vec /= norm
        return vec.tolist()
