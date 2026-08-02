"""Contract tests for ``integrations/hermes/_setup.py``.

Pins the Hermes-agnostic setup wizard:

- ``write_corti_toml`` emits a ``tomllib``-parseable file with
  ``[llm]`` / ``[embedding]`` (and ``[rerank]`` when provided) sections
  carrying the caller's keys, chmod 600, and omits ``[rerank]`` when None.
- ``post_setup`` in non-interactive mode writes ``corti.json`` (platform)
  or ``corti.toml`` + ``corti.json`` for oss mode, all parseable.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from hermes._setup import (
    build_corti_json,
    post_setup,
    write_corti_toml,
)

_TOML_MODE = 0o600


# ── write_corti_toml ───────────────────────────────────────────────────────


def test_write_corti_toml_sections_keys_and_mode(tmp_path: Path) -> None:
    path = write_corti_toml(
        tmp_path,
        llm={
            "model": "gpt-4",
            "api_key": "secret",
            "base_url": "http://llm",
            "timeout_seconds": 30,
            "max_retries": 2,
        },
        embedding={"model": "text-embed", "base_url": "http://emb"},
        rerank={"model": "rerank-1", "base_url": "http://rr"},
    )
    assert path == tmp_path / "corti.toml"
    assert path.exists()
    assert (path.stat().st_mode & 0o777) == _TOML_MODE
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    assert data["llm"]["model"] == "gpt-4"
    assert data["llm"]["api_key"] == "secret"
    assert data["llm"]["base_url"] == "http://llm"
    assert data["llm"]["timeout_seconds"] == 30
    assert data["llm"]["max_retries"] == 2
    assert data["embedding"]["model"] == "text-embed"
    assert data["embedding"]["base_url"] == "http://emb"
    assert data["rerank"]["model"] == "rerank-1"
    assert data["rerank"]["base_url"] == "http://rr"


def test_write_corti_toml_omits_rerank_when_none(tmp_path: Path) -> None:
    path = write_corti_toml(
        tmp_path,
        llm={"model": "m"},
        embedding={"model": "e"},
        rerank=None,
    )
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    assert "llm" in data
    assert "embedding" in data
    assert "rerank" not in data


# ── build_corti_json ───────────────────────────────────────────────────────


def test_build_corti_json_returns_expected_dict() -> None:
    payload = build_corti_json(
        api_url="http://api",
        mode="oss",
        user_id="u-1",
        agent_id="a-1",
        corti_root="/root",
    )
    assert payload == {
        "api_url": "http://api",
        "mode": "oss",
        "user_id": "u-1",
        "agent_id": "a-1",
        "corti_root": "/root",
    }


# ── post_setup ──────────────────────────────────────────────────────────────


def test_post_setup_platform_writes_only_corti_json(tmp_path: Path) -> None:
    hermes_home = tmp_path / "hermes"
    inputs = {
        "mode": "platform",
        "api_url": "http://api",
        "user_id": "u",
        "agent_id": "a",
    }
    payload = post_setup(hermes_home, {}, interactive=False, inputs=inputs)
    json_path = hermes_home / "corti.json"
    assert json_path.exists()
    assert (json_path.stat().st_mode & 0o777) == _TOML_MODE
    assert json.loads(json_path.read_text(encoding="utf-8")) == payload
    assert payload["mode"] == "platform"
    assert payload["corti_root"] is None
    # Platform mode does not write corti.toml under hermes_home.
    assert not (hermes_home / "corti.toml").exists()


def test_post_setup_oss_writes_toml_and_json(tmp_path: Path) -> None:
    hermes_home = tmp_path / "hermes"
    corti_root = tmp_path / "corti"
    inputs = {
        "mode": "oss",
        "corti_root": str(corti_root),
        "api_url": "http://api",
        "user_id": "u",
        "agent_id": "a",
        "llm": {"model": "m", "api_key": "k", "base_url": "http://llm"},
        "embedding": {"model": "e", "base_url": "http://emb"},
        "rerank": None,
    }
    payload = post_setup(hermes_home, {}, interactive=False, inputs=inputs)

    assert (hermes_home / "corti.json").exists()
    assert (corti_root / "corti.toml").exists()

    with (corti_root / "corti.toml").open("rb") as fh:
        toml_data = tomllib.load(fh)
    assert toml_data["llm"]["model"] == "m"
    assert toml_data["embedding"]["model"] == "e"
    assert "rerank" not in toml_data

    json_data = json.loads((hermes_home / "corti.json").read_text(encoding="utf-8"))
    assert json_data == payload
    assert json_data["mode"] == "oss"
    assert json_data["corti_root"] == str(corti_root)


def test_post_setup_oss_skips_ome_without_agent_track(tmp_path: Path) -> None:
    hermes_home = tmp_path / "hermes"
    corti_root = tmp_path / "corti"
    inputs = {
        "mode": "oss",
        "corti_root": str(corti_root),
        "llm": {"model": "m"},
        "embedding": {"model": "e"},
    }
    post_setup(hermes_home, {}, interactive=False, inputs=inputs)
    assert (corti_root / "corti.toml").exists()
    assert not (corti_root / "ome.toml").exists()
    assert (hermes_home / "corti.json").exists()
