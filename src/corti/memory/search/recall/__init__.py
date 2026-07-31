"""Per-kind recall layer.

External usage::

    from corti.memory.search.recall import (
        KindRecaller,
        RecallerDeps,
        EpisodeRecaller,
        AtomicFactRecaller,
        ProfileRecaller,
        KnowledgeTopicRecaller,
    )
"""

from .base import KindRecaller as KindRecaller
from .base import RecallerDeps as RecallerDeps
from .base import cosine_score_from_distance as cosine_score_from_distance
from .base import row_to_candidate as row_to_candidate

# ── PG recallers ─────────────────────────────────────────────────────────
from .pg_atomic_fact import PgAtomicFactRecaller as AtomicFactRecaller
from .pg_episode import PgEpisodeRecaller as EpisodeRecaller
from .pg_foresight import PgForesightRecaller as ForesightRecaller
from .pg_knowledge_topic import PgKnowledgeTopicRecaller as KnowledgeTopicRecaller
from .pg_profile import PgProfileRecaller as ProfileRecaller

__all__ = [
    "AtomicFactRecaller",
    "EpisodeRecaller",
    "ForesightRecaller",
    "KindRecaller",
    "KnowledgeTopicRecaller",
    "ProfileRecaller",
    "RecallerDeps",
    "cosine_score_from_distance",
    "row_to_candidate",
]
