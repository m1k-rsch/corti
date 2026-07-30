"""PG persistence adapter for Cortistrate — PostgreSQL 18.4 + pgvector 0.8.1.

PostgreSQL backend using
native SQL, psycopg3 async connections, and pgvector's HNSW index.

Exports:
    - ``init`` / ``dispose`` — lifecycle management
    - ``get_pool`` — async connection pool access
    - ``PgBaseModel`` — Pydantic base for table schemas
    - ``PgRepoBase`` / ``PgDailyLogRepoBase`` — generic CRUD
    - ``run_ddl`` — idempotent table + index creation
    - repo singletons
"""

from .base import PgBaseModel
from .ddl import run_ddl
from .pg_manager import dispose, get_pool, init
from .pg_repo import PgDailyLogRepoBase, PgRepoBase
from .repos import (
    atomic_fact_repo,
    episode_repo,
    foresight_repo,
    knowledge_topic_repo,
    user_profile_repo,
)
from .tables import (
    AtomicFact,
    Episode,
    Foresight,
    KnowledgeTopic,
    ParentType,
    UserProfile,
)

__all__ = [
    # Tables
    "Episode",
    "AtomicFact",
    "Foresight",
    "KnowledgeTopic",
    "ParentType",
    "UserProfile",
    # Repos
    "episode_repo",
    "atomic_fact_repo",
    "foresight_repo",
    "knowledge_topic_repo",
    "user_profile_repo",
    # Core
    "PgBaseModel",
    "PgRepoBase",
    "PgDailyLogRepoBase",
    # Lifecycle
    "init",
    "dispose",
    "get_pool",
    "run_ddl",
]
