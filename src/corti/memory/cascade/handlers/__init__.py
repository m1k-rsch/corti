"""Cascade handlers — one per kind, sharing the :class:`Handler` chassis.

Three daily-log handlers (episode / atomic_fact / foresight)
inherit :class:`BaseDailyLogHandler` for the shared
read / diff / upsert / delete loop; the per-kind subclass only
declares its repo binding and ``_build_row`` mapping. ``user_profile``
and ``knowledge_topic`` stand alone — they're
single-file kinds (no entries, no per-entry diff), so they implement
:class:`Handler` directly and own their reconcile loop.
"""

from .atomic_fact import AtomicFactHandler as AtomicFactHandler
from .base import Handler as Handler
from .base import HandlerDeps as HandlerDeps
from .episode import EpisodeHandler as EpisodeHandler
from .foresight import ForesightHandler as ForesightHandler
from .knowledge_document import KnowledgeDocumentHandler as KnowledgeDocumentHandler
from .knowledge_topic import KnowledgeTopicHandler as KnowledgeTopicHandler
from .user_profile import UserProfileHandler as UserProfileHandler

__all__ = [
    "AtomicFactHandler",
    "EpisodeHandler",
    "ForesightHandler",
    "Handler",
    "HandlerDeps",
    "KnowledgeDocumentHandler",
    "KnowledgeTopicHandler",
    "UserProfileHandler",
]
