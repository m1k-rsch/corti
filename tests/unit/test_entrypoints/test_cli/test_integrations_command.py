"""``corti integrations`` — installer CLI contract tests.

Pins the ``install`` / ``uninstall`` Typer commands against a fake bundle
directory and a throwaway ``HERMES_HOME``. Uses ``typer.testing.CliRunner``
only; no real HTTP, no real plugins loaded.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from corti.entrypoints.cli.commands import integrations as integrations_mod


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def hermes_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fake hermes home with HERMES_HOME set so _resolve_hermes_home picks it up."""
    # Note: the new code no longer reads HERMES_HOME for memory plugins;
    # it always uses ~/.hermes.  For tests we override the home dir directly
    # via monkeypatching the resolve function.
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setattr(
        integrations_mod, "_resolve_hermes_home", lambda: home
    )
    return home


@pytest.fixture
def claude_skills(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    skills = tmp_path / ".claude" / "skills"
    skills.mkdir(parents=True)
    monkeypatch.setattr(
        integrations_mod, "_resolve_claude_skills_dir", lambda: skills
    )
    return skills


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    src = tmp_path / "bundle"
    src.mkdir()
    (src / "plugin.yaml").write_text("name: corti\n")
    return src


# ── --help smoke ────────────────────────────────────────────────────────────


def test_install_help_exits_zero(runner: CliRunner):
    result = runner.invoke(integrations_mod.app, ["install", "--help"])
    assert result.exit_code == 0
    assert "hermes" in result.stdout
    assert "claude-code" in result.stdout


def test_uninstall_help_exits_zero(runner: CliRunner):
    result = runner.invoke(integrations_mod.app, ["uninstall", "--help"])
    assert result.exit_code == 0
    assert "hermes" in result.stdout


def test_status_help_exits_zero(runner: CliRunner):
    result = runner.invoke(integrations_mod.app, ["status", "--help"])
    assert result.exit_code == 0


# ── install ─────────────────────────────────────────────────────────────────


def _target(hermes_home: Path) -> Path:
    return hermes_home / "plugins" / "corti"


def _claude_target(claude_skills: Path) -> Path:
    return claude_skills / "corti"


def test_install_symlinks_hermes(runner: CliRunner, hermes_home: Path, bundle: Path):
    result = runner.invoke(
        integrations_mod.app, ["install", "hermes", "--source", str(bundle)]
    )
    assert result.exit_code == 0, result.output
    target = _target(hermes_home)
    assert target.is_symlink()
    assert target.resolve() == bundle.resolve()


def test_install_symlinks_claude(
    runner: CliRunner, claude_skills: Path, bundle: Path
):
    result = runner.invoke(
        integrations_mod.app, ["install", "claude-code", "--source", str(bundle)]
    )
    assert result.exit_code == 0, result.output
    target = _claude_target(claude_skills)
    assert target.is_symlink()


def test_install_is_idempotent(runner: CliRunner, hermes_home: Path, bundle: Path):
    args = ["install", "hermes", "--source", str(bundle)]
    first = runner.invoke(integrations_mod.app, args)
    second = runner.invoke(integrations_mod.app, args)
    assert first.exit_code == 0
    assert second.exit_code == 0
    target = _target(hermes_home)
    assert target.is_symlink()
    assert target.resolve() == bundle.resolve()


def test_install_refuses_real_dir_without_force(
    runner: CliRunner, hermes_home: Path, bundle: Path
):
    target = _target(hermes_home)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir()
    (target / "precious.txt").write_text("keep me")

    result = runner.invoke(
        integrations_mod.app,
        ["install", "hermes", "--source", str(bundle)],
        input="n\n",
    )
    assert result.exit_code == 1
    assert not target.is_symlink()
    assert (target / "precious.txt").exists()


def test_install_force_replaces_real_dir(
    runner: CliRunner, hermes_home: Path, bundle: Path
):
    target = _target(hermes_home)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir()
    (target / "old.txt").write_text("bye")

    result = runner.invoke(
        integrations_mod.app,
        ["install", "hermes", "--source", str(bundle), "--force"],
    )
    assert result.exit_code == 0, result.output
    assert target.is_symlink()
    assert target.resolve() == bundle.resolve()
    assert not (target / "old.txt").exists()


def test_install_missing_source_exits_nonzero(
    runner: CliRunner, hermes_home: Path, tmp_path: Path
):
    missing = tmp_path / "does-not-exist"
    result = runner.invoke(
        integrations_mod.app, ["install", "hermes", "--source", str(missing)]
    )
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_install_bad_target_exits_nonzero(runner: CliRunner):
    result = runner.invoke(
        integrations_mod.app, ["install", "nonexistent-agent"]
    )
    assert result.exit_code != 0


# ── uninstall ───────────────────────────────────────────────────────────────


def test_uninstall_removes_symlink(runner: CliRunner, hermes_home: Path, bundle: Path):
    runner.invoke(integrations_mod.app, ["install", "hermes", "--source", str(bundle)])
    target = _target(hermes_home)
    assert target.is_symlink()

    result = runner.invoke(integrations_mod.app, ["uninstall", "hermes"])
    assert result.exit_code == 0, result.output
    assert not target.exists()


def test_uninstall_refuses_real_dir(runner: CliRunner, hermes_home: Path, bundle: Path):
    target = _target(hermes_home)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir()

    result = runner.invoke(integrations_mod.app, ["uninstall", "hermes"])
    assert result.exit_code == 1
    assert target.is_dir()
    assert not target.is_symlink()


def test_uninstall_force_skips_bundle_check(
    runner: CliRunner, hermes_home: Path, tmp_path: Path
):
    """--force unlinks without prompting, even for non-corti targets."""
    other = tmp_path / "other"
    other.mkdir()
    target = _target(hermes_home)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(other, target_is_directory=True)

    result = runner.invoke(
        integrations_mod.app,
        ["uninstall", "hermes", "--force"],
    )
    assert result.exit_code == 0, result.output
    assert not target.exists()


def test_uninstall_refuses_non_corti_without_force(
    runner: CliRunner, hermes_home: Path, tmp_path: Path
):
    """Without --force, a non-corti symlink prompts and aborts on 'n'."""
    other = tmp_path / "other"
    other.mkdir()
    target = _target(hermes_home)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(other, target_is_directory=True)

    result = runner.invoke(
        integrations_mod.app,
        ["uninstall", "hermes"],
        input="n\n",
    )
    assert result.exit_code == 1
    assert target.is_symlink()


def test_uninstall_nothing_to_remove(runner: CliRunner, hermes_home: Path):
    result = runner.invoke(integrations_mod.app, ["uninstall", "hermes"])
    assert result.exit_code == 0
    assert "nothing to remove" in result.output.lower()


def test_uninstall_bad_target_exits_nonzero(runner: CliRunner):
    result = runner.invoke(
        integrations_mod.app, ["uninstall", "nonexistent-agent"]
    )
    assert result.exit_code != 0
