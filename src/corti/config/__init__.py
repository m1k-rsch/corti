"""Configuration data and Settings schema.

Public API:
    from corti.config import (
        Settings, MemorySettings, SqliteSettings,
        LLMSettings, EmbeddingSettings, RerankSettings,
        BoundaryDetectionSettings,
        load_settings, resolve_root,
    )

Distinct from ``corti.component.config`` (which is a *capability* -
loader / merger / env reader).
"""

from .settings import BoundaryDetectionSettings as BoundaryDetectionSettings
from .settings import EmbeddingSettings as EmbeddingSettings
from .settings import LLMSettings as LLMSettings
from .settings import MemorySettings as MemorySettings
from .settings import MultimodalSettings as MultimodalSettings
from .settings import RerankSettings as RerankSettings
from .settings import Settings as Settings
from .settings import SqliteSettings as SqliteSettings
from .settings import load_settings as load_settings
from .settings import resolve_root as resolve_root

__all__ = [
    "BoundaryDetectionSettings",
    "EmbeddingSettings",
    "LLMSettings",
    "MemorySettings",
    "MultimodalSettings",
    "RerankSettings",
    "Settings",
    "SqliteSettings",
    "load_settings",
    "resolve_root",
]
