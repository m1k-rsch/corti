"""PG table schema for user_profile."""

from __future__ import annotations

from typing import ClassVar

from corti.infra.persistence.pg.base import PgBaseModel


class UserProfile(PgBaseModel):
    """PG schema for ``user_profile`` table.

    Profile is a single-file kind: one ``users/<user_id>/user.md`` per
    user, replaced wholesale on edit. The PG row is a typed projection
    of the md frontmatter that the cascade keeps in sync.
    """

    TABLE_NAME: ClassVar[str] = "user_profile"
    BM25_FIELDS: ClassVar[list[str]] = []

    id: str
    owner_id: str
    owner_type: str
    app_id: str = "default"
    project_id: str = "default"
    summary: str
    explicit_info_json: str
    implicit_traits_json: str
    profile_timestamp_ms: int
    md_path: str
    content_sha256: str
    vector: list[float] = []
