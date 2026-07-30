"""Application settings.

Loaded by :func:`load_settings`. Source priority (later wins):

    1. ``config/default.toml`` (shipped values; lowest priority)
    2. ``<root>/cortistrate.toml`` (user config; optional; ``<root>`` resolved by
       :func:`resolve_root`)
    3. ``CORTISTRATE_<SECTION>__<KEY>`` environment variables
    4. Init args passed programmatically (highest priority)

The memory root is resolved by :func:`resolve_root`:
``explicit arg > CORTISTRATE_ROOT env > ~/.cortistrate``.

The settings tree mirrors the TOML structure: ``settings.sqlite.busy_timeout_ms``
maps to ``[sqlite].busy_timeout_ms`` and to ``CORTISTRATE_SQLITE__BUSY_TIMEOUT_MS``.

``load_settings`` is ``functools.cache``-d so callers in hot paths (e.g.
:mod:`cortistrate.component.utils.datetime`) don't re-parse the TOML on every
call. Tests that mutate environment variables must call
``load_settings.cache_clear()`` after the mutation to invalidate.
"""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

_DEFAULT_TOML_PATH = Path(__file__).parent / "default.toml"
_DEFAULT_ROOT = Path("~/.cortistrate")


def resolve_root(explicit: str | None = None) -> Path:
    """Resolve the memory-root path.

    Priority: explicit arg > CORTISTRATE_ROOT env > ~/.cortistrate default.

    Args:
        explicit: Caller-supplied path string (e.g. from ``--root`` CLI flag).

    Returns:
        Absolute resolved path to the memory root.
    """
    if explicit:
        return Path(explicit).expanduser().resolve()
    from_env = os.environ.get("CORTISTRATE_ROOT")
    if from_env:
        return Path(from_env).expanduser().resolve()
    return _DEFAULT_ROOT.expanduser().resolve()


class MemorySettings(BaseModel):
    """Memory configuration."""

    timezone: str = "UTC"
    """Effective timezone for date buckets and timestamps.

    Default ``"UTC"``. Override via ``[memory] timezone = "..."`` in
    TOML or ``CORTISTRATE_MEMORY__TIMEZONE`` env var. Validated against
    :class:`zoneinfo.ZoneInfo` at load time, so an invalid name fails
    fast (no silent fallback). This is the **sole** source of truth for
    the project's effective timezone — the OS ``TZ`` env var is *not*
    consulted, keeping the configuration deterministic.
    """

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"invalid timezone: {v!r}") from exc
        return v


class ApiSettings(BaseModel):
    """HTTP API server bind configuration.

    Default ``host = "127.0.0.1"`` keeps the server on loopback only,
    matching the threat model in ``SECURITY.md``: Cortistrate ships **no
    built-in authentication**, so binding to a routable interface
    (``0.0.0.0`` etc.) without your own gateway / auth layer in front
    is unsupported.

    Env binding:
        CORTISTRATE_API__HOST
        CORTISTRATE_API__PORT
    """

    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)


class SqliteSettings(BaseModel):
    """SQLite tunables applied as PRAGMAs on every new connection."""

    journal_mode: Literal["WAL", "DELETE", "MEMORY", "OFF", "TRUNCATE", "PERSIST"] = (
        "WAL"
    )
    synchronous: Literal["FULL", "NORMAL", "OFF", "EXTRA"] = "NORMAL"
    foreign_keys: bool = True
    temp_store: Literal["DEFAULT", "FILE", "MEMORY"] = "MEMORY"
    busy_timeout_ms: int = Field(default=5000, ge=0)
    journal_size_limit_bytes: int = Field(default=64 * 1024 * 1024, ge=0)
    cache_size_kb: int = Field(default=2048, ge=0)


class LLMSettings(BaseModel):
    """LLM client configuration.

    Read by the service layer when lazily constructing the LLM client
    handed to algo extractors. Provider-agnostic field names — the
    project follows the OpenAI API protocol so any OpenAI-compatible
    endpoint plugs in via ``base_url``.

    Env binding (via parent ``Settings``):
        CORTISTRATE_LLM__MODEL
        CORTISTRATE_LLM__API_KEY
        CORTISTRATE_LLM__BASE_URL
    """

    model: str = "gpt-4.1-mini"
    api_key: SecretStr | None = None
    base_url: str | None = None


class MultimodalSettings(BaseModel):
    """Multimodal parsing LLM config (everalgo-parser).

    Flat section mirroring ``[llm]``. The model must accept multimodal
    ``image_url`` parts (image / pdf / audio); it is kept independent from
    the main ``[llm]`` so parsing can target a vision/audio-capable
    endpoint without affecting boundary / extraction.

    Env binding (via parent ``Settings``):
        CORTISTRATE_MULTIMODAL__MODEL
        CORTISTRATE_MULTIMODAL__API_KEY
        CORTISTRATE_MULTIMODAL__BASE_URL
        CORTISTRATE_MULTIMODAL__MAX_CONCURRENCY
        CORTISTRATE_MULTIMODAL__FILE_URI_ALLOW_DIRS
        CORTISTRATE_MULTIMODAL__FILE_URI_MAX_BYTES
    """

    model: str = "google/gemini-3-flash-preview"
    api_key: SecretStr | None = None
    base_url: str | None = None
    max_concurrency: int = 4

    # ``file://`` content-item support (read locally by Cortistrate, not everalgo).
    file_uri_allow_dirs: list[str] = []
    """Allowlisted base dirs for ``file://`` uris. Empty = allow any readable
    file (permissive default); set to confine reads when the API is exposed."""
    file_uri_max_bytes: int = 50 * 1024 * 1024
    """Max size (bytes) of a ``file://`` asset; larger files are rejected."""


class EmbeddingSettings(BaseModel):
    """Embedding client configuration.

    OpenAI-compatible embedding endpoint. ``model`` / ``api_key`` /
    ``base_url`` are required at runtime when the embedding capability
    is enabled; the runtime knobs (``timeout`` etc.) have sensible
    defaults.

    Env binding:
        CORTISTRATE_EMBEDDING__MODEL
        CORTISTRATE_EMBEDDING__API_KEY
        CORTISTRATE_EMBEDDING__BASE_URL
        CORTISTRATE_EMBEDDING__TIMEOUT_SECONDS
        CORTISTRATE_EMBEDDING__MAX_RETRIES
        CORTISTRATE_EMBEDDING__BATCH_SIZE
        CORTISTRATE_EMBEDDING__MAX_CONCURRENT
    """

    model: str | None = None
    api_key: SecretStr | None = None
    base_url: str | None = None
    timeout_seconds: float = Field(default=30.0, gt=0)
    max_retries: int = Field(default=3, ge=0)
    batch_size: int = Field(default=10, ge=1)
    max_concurrent: int = Field(default=50, ge=1)


class RerankSettings(BaseModel):
    """Rerank client configuration.

    Unlike LLM / embedding (single OpenAI-compatible shape), rerank API
    schemas differ between providers — DeepInfra uses ``POST {base_url}/
    {model}`` with a custom body, vLLM uses ``POST {base_url}/rerank``
    with ``{model, query, documents}``. ``provider`` picks which client
    implementation the factory builds.

    Env binding:
        CORTISTRATE_RERANK__PROVIDER
        CORTISTRATE_RERANK__MODEL
        CORTISTRATE_RERANK__API_KEY
        CORTISTRATE_RERANK__BASE_URL
        CORTISTRATE_RERANK__TIMEOUT_SECONDS
        CORTISTRATE_RERANK__MAX_RETRIES
        CORTISTRATE_RERANK__BATCH_SIZE
        CORTISTRATE_RERANK__MAX_CONCURRENT
    """

    provider: Literal["deepinfra", "vllm", "dashscope"] = "deepinfra"
    model: str | None = None
    api_key: SecretStr | None = None
    base_url: str | None = None
    timeout_seconds: float = Field(default=30.0, gt=0)
    max_retries: int = Field(default=3, ge=0)
    batch_size: int = Field(default=10, ge=1)
    max_concurrent: int = Field(default=50, ge=1)


class BoundaryDetectionSettings(BaseModel):
    """Hard limits passed through to ``everalgo`` BoundaryDetector."""

    hard_token_limit: int = Field(default=65536, ge=1)
    hard_msg_limit: int = Field(default=500, ge=1)


class MemorizeSettings(BaseModel):
    """Memorize use-case configuration.

    ``mode`` selects which boundary detector runs and which pipelines are
    dispatched. A service process serves one mode at a time; toggling
    requires a restart.

        - ``"chat"``  -> ``everalgo.user_memory.BoundaryDetector`` and only the
          user-memory pipeline runs.
        - ``"agent"`` -> ``everalgo.agent_memory.AgentBoundaryDetector`` and
          both user-memory + agent-memory pipelines run.

    ``session_lock_timeout_seconds`` caps how long one ``memorize()``
    invocation can hold the per-session lock. Covers boundary LLM call +
    memcell DB writes + (synchronous portion of) pipeline dispatch. Stops
    a stuck LLM from deadlocking subsequent concurrent calls on the same
    session_id: on timeout the outer ``asyncio.timeout`` cancels the task
    and the lock auto-releases.

    Env binding:
        CORTISTRATE_MEMORIZE__MODE
        CORTISTRATE_MEMORIZE__SESSION_LOCK_TIMEOUT_SECONDS
    """

    mode: Literal["chat", "agent"] = "agent"
    session_lock_timeout_seconds: float = Field(default=360.0, gt=0)


class ClusteringSettings(BaseModel):
    """Geometry-clustering tunables.

    Env binding:
        CORTISTRATE_CLUSTERING__THRESHOLD
        CORTISTRATE_CLUSTERING__TIME_WINDOW_DAYS
    """

    threshold: float = Field(default=0.65, gt=0, le=1)
    time_window_days: float = Field(default=7.0, gt=0)


class KnowledgeSearchSettings(BaseModel):
    """``[knowledge.search]`` — retrieval tuning for the knowledge module."""

    recall_n: int = 200
    rerank_n: int = 50
    mass_top_m: int = 50
    lam: float = Field(0.1, alias="lambda")
    top_k_cap: int = 100

    model_config = ConfigDict(populate_by_name=True)


class KnowledgeSettings(BaseModel):
    """``[knowledge]`` — knowledge module configuration."""

    max_upload_bytes: int = 52_428_800  # 50 MiB
    search: KnowledgeSearchSettings = KnowledgeSearchSettings()


class Settings(BaseSettings):
    """Top-level application settings."""

    memory: MemorySettings = MemorySettings()
    api: ApiSettings = ApiSettings()
    sqlite: SqliteSettings = SqliteSettings()
    llm: LLMSettings = LLMSettings()
    embedding: EmbeddingSettings = EmbeddingSettings()
    rerank: RerankSettings = RerankSettings()
    boundary_detection: BoundaryDetectionSettings = BoundaryDetectionSettings()
    memorize: MemorizeSettings = MemorizeSettings()
    clustering: ClusteringSettings = ClusteringSettings()
    multimodal: MultimodalSettings = MultimodalSettings()
    knowledge: KnowledgeSettings = KnowledgeSettings()

    model_config = SettingsConfigDict(
        env_prefix="CORTISTRATE_",
        env_nested_delimiter="__",
        toml_file=_DEFAULT_TOML_PATH,
        extra="ignore",
    )

    def __init__(self, *, _cortistrate_root: Path | None = None, **kwargs: object) -> None:
        """Initialise settings, optionally pinning the memory-root for testing.

        Args:
            _cortistrate_root: Override the memory root used to locate
                ``cortistrate.toml``. Intended for tests only; pass ``None``
                (the default) in production to use :func:`resolve_root`.
            **kwargs: Forwarded verbatim to :class:`pydantic_settings.BaseSettings`.
        """
        if _cortistrate_root is not None:
            # Temporarily inject CORTISTRATE_ROOT so that settings_customise_sources
            # (a classmethod that cannot access instance state) picks it up via
            # resolve_root().  We restore the original value after super().__init__
            # returns to avoid leaking the override into the process environment.
            _prev = os.environ.get("CORTISTRATE_ROOT")
            os.environ["CORTISTRATE_ROOT"] = str(_cortistrate_root)
            try:
                super().__init__(**kwargs)
            finally:
                if _prev is None:
                    os.environ.pop("CORTISTRATE_ROOT", None)
                else:
                    os.environ["CORTISTRATE_ROOT"] = _prev
        else:
            super().__init__(**kwargs)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Source order: init_args > env_vars > cortistrate.toml > default.toml."""
        sources: list[PydanticBaseSettingsSource] = [
            init_settings,
            env_settings,
        ]
        # Attempt to load <root>/cortistrate.toml if it exists.
        cortistrate_toml = resolve_root() / "cortistrate.toml"
        if cortistrate_toml.is_file():
            sources.append(
                TomlConfigSettingsSource(settings_cls, toml_file=cortistrate_toml)
            )
        sources.append(TomlConfigSettingsSource(settings_cls))  # default.toml
        return tuple(sources)


@cache
def load_settings() -> Settings:
    """Load settings from default.toml + environment variables (cached).

    Cached at the module level — every caller sees the same instance until
    something explicitly clears the cache (``load_settings.cache_clear()``).
    Tests that monkeypatch environment variables must call
    ``cache_clear`` after each mutation to pick the new env up.
    """
    return Settings()
