"""HTTP API lifespan providers.

Concrete :class:`corti.core.lifespan.LifespanProvider` implementations
for the storage + chassis backends this entrypoint composes. They live next to
``app.py`` because they are *application-bootstrap* details, not
generic chassis: a different deployment mode (CLI, embedded, batch
worker) may compose a different set of providers.

External usage::

    from corti.entrypoints.api.lifespans import (
        LLMLifespanProvider,
        SqliteLifespanProvider,
        PGLifespanProvider,
        CascadeLifespanProvider,
        OmeLifespanProvider,
    )
"""

from .cascade import CascadeLifespanProvider as CascadeLifespanProvider
from .llm import LLMLifespanProvider as LLMLifespanProvider
from .ome import OmeLifespanProvider as OmeLifespanProvider
from .pg import PGLifespanProvider as PGLifespanProvider
from .sqlite import SqliteLifespanProvider as SqliteLifespanProvider

__all__ = [
    "CascadeLifespanProvider",
    "LLMLifespanProvider",
    "OmeLifespanProvider",
    "PGLifespanProvider",
    "SqliteLifespanProvider",
]
