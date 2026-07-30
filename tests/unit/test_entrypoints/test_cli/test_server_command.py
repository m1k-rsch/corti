"""``cortistrate server start`` — argument resolution + uvicorn handoff.

Uvicorn ``run`` is the external boundary and is mocked. We assert the
host/port/log_level resolution chain (CLI flag > env > default) and the
KeyboardInterrupt / OSError exit paths.
"""

from __future__ import annotations

import os

import pytest
from typer.testing import CliRunner

from cortistrate.entrypoints.cli.commands import server as server_mod
from cortistrate.entrypoints.cli.main import app as root_app


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Strip CORTISTRATE_* env vars so default resolution is deterministic."""
    for k in list(os.environ):
        if k.startswith("CORTISTRATE_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("CORTISTRATE_LOG_LEVEL", raising=False)
    monkeypatch.setenv("CORTISTRATE_ROOT", str(tmp_path))
    (tmp_path / "cortistrate.toml").write_text("# test\n")
    from cortistrate.config import load_settings

    load_settings.cache_clear()


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Mock ``uvicorn.run`` and return the kwargs it was called with."""
    captured: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> None:
        captured["args"] = args
        captured["kwargs"] = kwargs

    monkeypatch.setattr(server_mod.uvicorn, "run", fake_run)
    return captured


def test_start_uses_default_host_port_log_level(captured: dict[str, object]) -> None:
    result = CliRunner().invoke(root_app, ["server", "start"])
    assert result.exit_code == 0, result.stdout
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8000
    assert kwargs["log_level"] == "info"
    assert kwargs["factory"] is True
    args = captured["args"]
    assert args == ("cortistrate.entrypoints.api.app:create_app",)


def test_start_cli_flags_override_env(
    captured: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CORTISTRATE_API__HOST", "1.2.3.4")
    monkeypatch.setenv("CORTISTRATE_API__PORT", "9000")
    monkeypatch.setenv("CORTISTRATE_API__LOG_LEVEL", "debug")
    from cortistrate.config import load_settings

    load_settings.cache_clear()
    result = CliRunner().invoke(
        root_app,
        [
            "server",
            "start",
            "--host",
            "127.0.0.1",
            "--port",
            "8765",
            "--log-level",
            "warning",
        ],
    )
    assert result.exit_code == 0, result.stdout
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8765
    assert kwargs["log_level"] == "warning"


def test_start_falls_back_to_env_when_flags_omitted(
    captured: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CORTISTRATE_API__HOST", "10.0.0.1")
    monkeypatch.setenv("CORTISTRATE_API__PORT", "8765")
    from cortistrate.config import load_settings

    load_settings.cache_clear()
    result = CliRunner().invoke(root_app, ["server", "start"])
    assert result.exit_code == 0, result.stdout
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["host"] == "10.0.0.1"
    assert kwargs["port"] == 8765


def test_start_swallows_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(server_mod.uvicorn, "run", boom)
    result = CliRunner().invoke(root_app, ["server", "start"])
    assert result.exit_code == 0


def test_start_exits_one_on_os_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise OSError("port in use")

    monkeypatch.setattr(server_mod.uvicorn, "run", boom)
    result = CliRunner().invoke(root_app, ["server", "start"])
    assert result.exit_code == 1


def test_start_with_root_option(
    captured: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    """``--root`` sets CORTISTRATE_ROOT for settings resolution."""
    from cortistrate.config import load_settings

    load_settings.cache_clear()
    result = CliRunner().invoke(root_app, ["server", "start", "--root", str(tmp_path)])
    assert result.exit_code == 0, result.stdout
    assert "kwargs" in captured
