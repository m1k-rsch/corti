"""Pydantic base for PG-backed tables (no Arrow deps).

Mirrors the role of ``BaseDbTable`` but for PostgreSQL. Carries
``TABLE_NAME`` + ``BM25_FIELDS`` as ClassVars so repos / recallers
read the table name and tsvector column list from the schema alone.

Unlike the original Arrow-backed backend:
- Inherits from ``pydantic.BaseModel`` directly (no Arrow schema conversion).
- ``vector`` / ``subject_vector`` are ``list[float] | None`` — pgvector
  serialises them as ``'[0.1,0.2,...]'`` strings; the repo layer handles
  the conversion.
"""

from __future__ import annotations

import datetime as _dt
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from corti.component.utils.datetime import get_utc_now


class PgBaseModel(BaseModel):
    """Pydantic schema for one PG business table.

    Subclasses declare their columns as fields and override
    :attr:`TABLE_NAME` + :attr:`BM25_FIELDS`. The model is **validation
    only** — the DDL (``ddl.py``) owns the SQL shape. The repo layer
    converts between Pydantic instances and psycopg row dicts.
    """

    model_config = ConfigDict(extra="forbid")

    TABLE_NAME: ClassVar[str] = ""
    """PG table name. Business schemas must override."""

    BM25_FIELDS: ClassVar[list[str]] = []
    """Columns whose ``*_tokens`` counterpart has a tsvector GIN index.

    Each entry is the ``*_tokens`` column name (e.g. ``"episode_tokens"``);
    the recaller uses this list to build ``plainto_tsquery`` + ``ts_rank_cd``
    SQL for BM25 recall.
    """

    created_at: _dt.datetime = Field(default_factory=get_utc_now)
    updated_at: _dt.datetime = Field(default_factory=get_utc_now)


def touch(record: PgBaseModel) -> PgBaseModel:
    """Set ``record.updated_at = now`` and return the record (chainable)."""
    record.updated_at = get_utc_now()
    return record
