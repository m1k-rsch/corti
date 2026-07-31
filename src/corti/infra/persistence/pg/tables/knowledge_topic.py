"""PG table schema for knowledge_topic."""

from __future__ import annotations

from typing import ClassVar

from corti.infra.persistence.pg.base import PgBaseModel


class KnowledgeTopic(PgBaseModel):
    """PG schema for ``knowledge_topic`` table."""

    TABLE_NAME: ClassVar[str] = "knowledge_topic"
    BM25_FIELDS: ClassVar[list[str]] = ["summary_tokens", "content_tokens"]

    id: str
    doc_id: str
    category_id: str
    app_id: str
    project_id: str
    topic_name: str
    topic_path: str
    depth: int
    parent_node_id: str = ""
    summary: str
    summary_tokens: str = ""
    content_tokens: str = ""
    content_labels: list[str] = []
    md_path: str
    content_sha256: str
    vector: list[float] = []
