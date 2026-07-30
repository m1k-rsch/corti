"""SQLite + Postgres lifespan providers — startup wires singletons, shutdown disposes."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI

from cortistrate.entrypoints.api.lifespans import SqliteLifespanProvider
from cortistrate.infra.persistence.sqlite import sqlite_manager


@pytest.fixture(autouse=True)
async def _reset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect both managers at an isolated memory-root."""
    monkeypatch.setenv("CORTISTRATE_ROOT", str(tmp_path))
    sqlite_manager._engine = None
    sqlite_manager._session_factory = None
    yield
    await sqlite_manager.dispose_engine()


async def test_sqlite_provider_startup_builds_engine_and_creates_schema(
    tmp_path: Path,
) -> None:
    provider = SqliteLifespanProvider()
    app = FastAPI()

    engine = await provider.startup(app)

    assert engine is sqlite_manager.get_engine()  # singleton wired
    assert (
        tmp_path / ".index" / "sqlite" / "system.db"
    ).exists()  # schema create_all opened the file


async def test_sqlite_provider_shutdown_disposes_singleton() -> None:
    provider = SqliteLifespanProvider()
    app = FastAPI()
    await provider.startup(app)
    assert sqlite_manager._engine is not None

    await provider.shutdown(app)
    assert sqlite_manager._engine is None



