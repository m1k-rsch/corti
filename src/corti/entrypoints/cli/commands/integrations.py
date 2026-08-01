"""``corti integrations`` — install Corti bundles into agent runtimes.

Supports Hermes Agent and Claude Code.  Installs by symlinking from the agent's
plugin directory into the pip-installed integration bundle (shipped as
``src/integrations/{hermes,claude-code}/``).

Auto-detect runs once per environment (guarded by
``~/.corti/.integrations-sentinel``) on first ``corti``
invocation after installation.
"""

from __future__ import annotations

import importlib
import shutil
from contextlib import suppress
from pathlib import Path

import typer

from corti.core.observability.logging import get_logger

app = typer.Typer(
    name="integrations",
    help="Install Corti integrations into agent runtimes.",
    no_args_is_help=True,
)

logger = get_logger(__name__)

# ── constants ─────────────────────────────────────────────────────────────────

_HERMES_TARGET = "hermes"
_CLAUDE_TARGET = "claude-code"
_SUPPORTED = frozenset({_HERMES_TARGET, _CLAUDE_TARGET})

# Directory name inside src/integrations/ — not the CLI arg.
_BUNDLE_DIRS: dict[str, str] = {
    _HERMES_TARGET: "hermes",
    _CLAUDE_TARGET: "claude-code",
}

# Where each agent expects user-installed plugins.
_HERMES_PLUGIN_SUBDIR = Path("plugins") / "corti"
_CLAUDE_SKILLS_SUBDIR = Path("skills") / "corti"

# Sentinel file — written after first auto-detect so we never scan twice.
_SENTINEL = Path.home() / ".corti" / ".integrations-sentinel"


# ── bundle source resolution ─────────────────────────────────────────────────


def _resolve_bundle_root() -> Path | None:
    """Return the ``integrations/`` directory shipped in the pip package.

    Priority:
    1. ``import integrations`` → ``integrations.__path__[0]`` (pip-installed)
    2. Walk up from ``corti.__file__`` → ``src/integrations/`` (dev checkout)
    """

    # Pip-installed: the integrations namespace lives next to corti.
    try:
        import corti
    except ImportError:
        corti = None  # type: ignore[assignment]

    try:
        pkg = importlib.import_module("integrations")
        if hasattr(pkg, "__path__") and pkg.__path__:
            return Path(pkg.__path__[0]).resolve()
    except ImportError:
        pass

    # Dev checkout: walk up from corti's location.
    if corti is not None:
        try:
            here = Path(corti.__file__).resolve()
            for parent in here.parents:
                candidate = parent / "integrations"
                if candidate.is_dir():
                    return candidate.resolve()
        except (AttributeError, TypeError):
            pass

    return None


def _resolve_target_bundle(target: str, explicit: str | None = None) -> Path:
    """Return the absolute path to the integration bundle for ``target``.

    When ``explicit`` is given (``--source``), it IS the bundle directory.
    When auto-resolving, the target dir name is appended to the bundle root.
    """
    if explicit:
        bundle = Path(explicit).expanduser().resolve()
        if not bundle.is_dir():
            raise typer.BadParameter(f"Integration bundle not found: {bundle}")
        return bundle

    bundle_root = _resolve_bundle_root()
    if bundle_root is None:
        raise typer.BadParameter(
            "Could not locate the integrations bundle. "
            "Ensure corti is installed via pip, or pass --source PATH."
        )

    dir_name = _BUNDLE_DIRS[target]
    bundle = bundle_root / dir_name
    if not bundle.is_dir():
        raise typer.BadParameter(f"Integration bundle not found: {bundle}")
    return bundle


# ── agent home resolution ────────────────────────────────────────────────────


def _resolve_hermes_home() -> Path:
    """Return the shared Hermes home, NOT a profile-specific directory.

    ``HERMES_HOME`` env var may point to ``~/.hermes/profiles/<name>/``
    (profile-scoped), but user-installed memory provider plugins must
    live under ``~/.hermes/plugins/`` where the memory provider loader
    actually scans.  We always use the platform default hermes home.
    """
    return Path("~/.hermes").expanduser().resolve()


def _resolve_claude_skills_dir() -> Path:
    return Path("~/.claude/skills").expanduser().resolve()


def _agent_is_installed(target: str) -> bool:
    """Best-effort detection: does the agent's home directory exist?"""
    if target == _HERMES_TARGET:
        return _resolve_hermes_home().is_dir()
    if target == _CLAUDE_TARGET:
        # Claude Code creates ~/.claude/ on first run.
        return (Path("~/.claude").expanduser() / "settings.json").exists()
    return False


# ── install / uninstall ──────────────────────────────────────────────────────


def _install_hermes(bundle_src: Path, force: bool = False) -> Path:
    """Symlink ``~/.hermes/plugins/corti`` → ``bundle_src``."""
    target_path = _resolve_hermes_home() / _HERMES_PLUGIN_SUBDIR
    _do_symlink(target_path, bundle_src, force)
    return target_path


def _install_claude(bundle_src: Path, force: bool = False) -> Path:
    """Symlink ``~/.claude/skills/corti`` → ``bundle_src``."""
    skills_dir = _resolve_claude_skills_dir()
    skills_dir.mkdir(parents=True, exist_ok=True)
    target_path = skills_dir / "corti"
    _do_symlink(target_path, bundle_src, force)
    return target_path


def _do_symlink(target: Path, source: Path, force: bool) -> None:
    """Create or replace a directory symlink at ``target``."""
    if target.is_symlink():
        target.unlink()
    elif target.exists():
        if target.is_dir():
            if not force:
                confirm = typer.confirm(
                    f"{target} is a real directory. Replace with symlink to bundle?",
                    default=False,
                )
                if not confirm:
                    typer.echo("Aborted; target left untouched.")
                    raise typer.Exit(code=1)
            shutil.rmtree(target)
        else:
            typer.echo(
                f"Refusing to replace {target}: not a directory or symlink. "
                "Remove it manually and re-run."
            )
            raise typer.Exit(code=1)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(source, target_is_directory=True)


def _is_installed(target: str) -> bool:
    """Check if the plugin symlink already exists."""
    if target == _HERMES_TARGET:
        link = _resolve_hermes_home() / _HERMES_PLUGIN_SUBDIR
    else:
        link = _resolve_claude_skills_dir() / "corti"
    return link.is_symlink() or link.is_dir()


# ── CLI commands ─────────────────────────────────────────────────────────────


@app.command("install")
def install(
    target: str = typer.Argument(
        ...,
        help="Agent target: 'hermes' or 'claude-code'",
    ),
    source: str | None = typer.Option(
        None,
        "--source",
        help="Override the bundle source path (default: pip-installed location).",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite an existing real directory at the target path.",
    ),
) -> None:
    """Symlink the Corti integration into an agent's plugin directory."""
    if target not in _SUPPORTED:
        raise typer.BadParameter(
            f"Unsupported target: {target!r}. "
            f"Supported: {', '.join(sorted(_SUPPORTED))}."
        )

    bundle_src = _resolve_target_bundle(target, source)

    if target == _HERMES_TARGET:
        link = _install_hermes(bundle_src, force)
        typer.secho(f"linked: {link} -> {bundle_src}", fg=typer.colors.GREEN)
        typer.echo(
            "\nNext:\n"
            "  1. Run `hermes memory setup` and select 'corti'.\n"
            "  2. Verify: `hermes corti status`."
        )
    else:
        link = _install_claude(bundle_src, force)
        typer.secho(f"linked: {link} -> {bundle_src}", fg=typer.colors.GREEN)
        typer.echo(
            "\nNext:\n"
            "  Start Claude Code. The plugin loads as corti@skills-dir.\n"
            "  Verify: run `/corti:mem-search \"test\"` in Claude Code."
        )


@app.command("uninstall")
def uninstall(
    target: str = typer.Argument(
        ...,
        help="Agent target: 'hermes' or 'claude-code'",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Unlink even if the symlink doesn't point to a corti bundle.",
    ),
) -> None:
    """Remove the Corti integration symlink."""
    if target not in _SUPPORTED:
        raise typer.BadParameter(
            f"Unsupported target: {target!r}. "
            f"Supported: {', '.join(sorted(_SUPPORTED))}."
        )

    if target == _HERMES_TARGET:
        link = _resolve_hermes_home() / _HERMES_PLUGIN_SUBDIR
    else:
        link = _resolve_claude_skills_dir() / "corti"

    if not link.exists() and not link.is_symlink():
        typer.echo(f"Nothing to remove: {link} does not exist.")
        return

    if link.is_dir() and not link.is_symlink():
        typer.echo(
            f"Refusing to remove {link}: it is a real directory, not a symlink. "
            "Remove it manually if you really intend to."
        )
        raise typer.Exit(code=1)

    if not link.is_symlink():
        typer.echo(f"Refusing to remove {link}: not a symlink.")
        raise typer.Exit(code=1)

    if not force:
        # Quick sanity: does the symlink point at something that looks like corti?
        resolved = link.resolve()
        if not (resolved / "plugin.yaml").exists() and not (
            resolved / ".claude-plugin" / "plugin.json"
        ).exists():
            msg = (
                f"{link} does not appear to point to a corti "
                "bundle. Remove anyway?"
            )
            confirm = typer.confirm(msg, default=False)
            if not confirm:
                typer.echo("Aborted.")
                raise typer.Exit(code=1)

    link.unlink()
    typer.secho(f"removed: {link}", fg=typer.colors.GREEN)
    if target == _HERMES_TARGET:
        typer.echo(
            "The `memory.provider` setting in Hermes was left untouched. "
            "Reset it with: hermes config set memory.provider ''"
        )


@app.command("status")
def status() -> None:
    """Show which agents are detected and whether integrations are installed."""
    typer.echo("Corti integrations\n")

    for target in sorted(_SUPPORTED):
        agent_detected = _agent_is_installed(target)
        installed = _is_installed(target) if agent_detected else False
        status_str = "installed ✓" if installed else "not installed"
        agent_str = "detected" if agent_detected else "not detected"
        typer.echo(f"  {target:12s}  agent: {agent_str:12s}  plugin: {status_str}")


# ── auto-detect (called on first CLI invocation) ─────────────────────────────


def auto_detect_and_install(
    _app: typer.Typer | None = None,
    _ctx: typer.Context | None = None,
) -> None:
    """Run once per environment: detect agents, silently install plugins.

    Skipped in dev checkouts — only fires for real installs (Docker /
    site-packages). The sentinel file prevents repeat work.
    """
    # Guard: dev checkout users don't need auto-install.
    import sys

    import corti

    pkg = Path(corti.__file__).resolve()
    in_site = any(
        "site-packages" in p and pkg.is_relative_to(Path(p).resolve())
        for p in sys.path
    )
    if not in_site:
        return

    if _SENTINEL.exists():
        return

    _SENTINEL.parent.mkdir(parents=True, exist_ok=True)
    _SENTINEL.touch()

    try:
        bundle_src = _resolve_bundle_root()
        if bundle_src is None:
            logger.debug("auto_detect: no integrations bundle found, skipping")
            return
    except Exception:
        return

    for target in sorted(_SUPPORTED):
        if not _agent_is_installed(target):
            continue
        with suppress(Exception):
            _install_silent(target, bundle_src)


def _install_silent(target: str, bundle_root: Path) -> None:
    """Silent install — no prompts, no output. Used by auto-detect."""
    dir_name = _BUNDLE_DIRS[target]
    bundle_src = bundle_root / dir_name
    if not bundle_src.is_dir():
        return

    if _is_installed(target):
        return

    if target == _HERMES_TARGET:
        _install_hermes(bundle_src, force=True)
    else:
        _install_claude(bundle_src, force=True)
    logger.info(
        "corti.integration.auto_installed",
        target=target,
        source=str(bundle_src),
    )
