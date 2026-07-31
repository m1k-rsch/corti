"""Business markdown readers — symmetric with the writers.

Daily-log markdown is parsed via :class:`MarkdownReader` from ``core``
(the base reader returns frontmatter dict + body + entry markers, all
schema-agnostic). Reader classes here add the **business-aware
locator** layer:

    * :class:`BaseDailyReader` + subclasses — bind a daily-log schema,
      resolve ``(scope_id, date)`` to a file, locate entries by id,
      and optionally upgrade to :class:`StructuredEntry`. Symmetric
      with :class:`BaseDailyWriter`.
    * :class:`ProfileReader` — reads a fixed-name profile file
      (``user.md`` / ``agent.md`` / ``soul.md`` / …) and parses its
      frontmatter into the caller-supplied schema.

By design, no batch / list APIs live here: bulk enumeration for
prompt-budget or cross-record queries goes through sqlite/postgres
(see the cascade daemon's index sync), not a markdown directory walk.

External usage::

    from corti.infra.persistence.markdown.readers import (
        BaseDailyReader,
        EpisodeReader,
        ProfileReader,
    )
"""

from .atomic_fact_reader import AtomicFactReader as AtomicFactReader
from .base import BaseDailyReader as BaseDailyReader
from .episode_reader import EpisodeReader as EpisodeReader
from .foresight_reader import ForesightReader as ForesightReader
from .profile_reader import ProfileReader as ProfileReader
from .taxonomy_reader import ensure_taxonomy as ensure_taxonomy
from .taxonomy_reader import parse_taxonomy as parse_taxonomy

__all__ = [
    "AtomicFactReader",
    "BaseDailyReader",
    "EpisodeReader",
    "ForesightReader",
    "ProfileReader",
    "ensure_taxonomy",
    "parse_taxonomy",
]
