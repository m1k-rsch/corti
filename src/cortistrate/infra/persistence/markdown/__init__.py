"""Markdown business persistence layer.

Sits on top of :mod:`cortistrate.core.persistence.markdown` (atomic write +
parse + frontmatter chassis) and provides:

    * concrete frontmatter schemas under :mod:`.mds`
    * concrete business writers under :mod:`.writers`
      (``BaseDailyWriter`` + subclasses, ``ProfileWriter``)
    * concrete business readers under :mod:`.readers`
      (``BaseDailyReader`` + subclasses, ``ProfileReader``)

External usage::

    from cortistrate.infra.persistence.markdown import (
        BaseDailyWriter, BaseDailyReader,
        EpisodeWriter, EpisodeReader, EpisodeDailyFrontmatter,
        AtomicFactDailyFrontmatter,
        ForesightDailyFrontmatter,
        ProfileWriter, ProfileReader,
    )

Outer layers MUST go through this top-level package because
``infra.persistence.markdown.**`` (sub-packages) are forbidden to outer
layers by import-linter.
"""

from .mds import AtomicFactDailyFrontmatter as AtomicFactDailyFrontmatter
from .mds import EpisodeDailyFrontmatter as EpisodeDailyFrontmatter
from .mds import ForesightDailyFrontmatter as ForesightDailyFrontmatter
from .mds import KnowledgeDocumentFrontmatter as KnowledgeDocumentFrontmatter
from .mds import KnowledgeTopicFrontmatter as KnowledgeTopicFrontmatter
from .mds import UserProfileFrontmatter as UserProfileFrontmatter
from .readers import AtomicFactReader as AtomicFactReader
from .readers import BaseDailyReader as BaseDailyReader
from .readers import EpisodeReader as EpisodeReader
from .readers import ForesightReader as ForesightReader
from .readers import ProfileReader as ProfileReader
from .readers import ensure_taxonomy as ensure_taxonomy
from .readers import parse_taxonomy as parse_taxonomy
from .writers import AtomicFactWriter as AtomicFactWriter
from .writers import BaseDailyWriter as BaseDailyWriter
from .writers import EpisodeWriter as EpisodeWriter
from .writers import ForesightWriter as ForesightWriter
from .writers import KnowledgeWriter as KnowledgeWriter
from .writers import ProfileWriter as ProfileWriter

__all__ = [
    "AtomicFactDailyFrontmatter",
    "AtomicFactReader",
    "AtomicFactWriter",
    "BaseDailyReader",
    "BaseDailyWriter",
    "EpisodeDailyFrontmatter",
    "EpisodeReader",
    "EpisodeWriter",
    "ForesightDailyFrontmatter",
    "ForesightReader",
    "ForesightWriter",
    "KnowledgeDocumentFrontmatter",
    "KnowledgeTopicFrontmatter",
    "KnowledgeWriter",
    "ProfileReader",
    "ProfileWriter",
    "UserProfileFrontmatter",
    "ensure_taxonomy",
    "parse_taxonomy",
]
