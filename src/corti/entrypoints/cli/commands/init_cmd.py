"""``corti init`` — generate starter config files in the memory root.

Copies the shipped ``default.toml`` and ``default_ome.toml`` templates
into the resolved memory root as ``corti.toml`` and ``ome.toml``
respectively. Users then edit these files to fill in API keys and tune
strategy schedules.

Subcommand mounted as ``corti init`` (top-level leaf command — not a
Typer group), to match the idiomatic ``alembic init`` / ``django-admin
startproject`` shape.
"""

from __future__ import annotations

from pathlib import Path

import typer

from corti.config.settings import resolve_root

_CORTI_TEMPLATE = Path(__file__).resolve().parents[3] / "config" / "default.toml"
_OME_TEMPLATE = Path(__file__).resolve().parents[3] / "config" / "default_ome.toml"


def register(parent: typer.Typer) -> None:
    """Attach the ``init`` command to the root CLI app."""

    @parent.command("init")
    def init(
        root: str | None = typer.Option(
            None,
            "--root",
            help="Memory root directory (default: ~/.corti)",
        ),
        force: bool = typer.Option(
            False,
            "--force",
            help="Overwrite existing files",
        ),
        print_: bool = typer.Option(
            False,
            "--print",
            help="Print the corti.toml template to stdout instead of writing to disk.",
        ),
    ) -> None:
        """Generate starter configuration files.

        Common flows::

            corti init                     # writes to ~/.corti/
            corti init --root /data/corti # writes to /data/corti/
            corti init --force             # overwrites existing files
            corti init --print             # prints corti.toml to stdout

        Exit codes:

        - 0 — files created successfully (or printed to stdout).
        - 1 — files already exist and ``--force`` was not given.
        """
        if print_:
            import sys

            sys.stdout.write(_CORTI_TEMPLATE.read_text(encoding="utf-8"))
            return

        resolved = resolve_root(root)
        resolved.mkdir(parents=True, exist_ok=True)

        corti_toml = resolved / "corti.toml"
        ome_toml = resolved / "ome.toml"

        created: list[Path] = []
        for target, template in [
            (corti_toml, _CORTI_TEMPLATE),
            (ome_toml, _OME_TEMPLATE),
        ]:
            if target.exists() and not force:
                typer.echo(f"  exists: {target} (skipped)")
                continue
            target.write_bytes(template.read_bytes())
            created.append(target)
            typer.secho(f"  created: {target}", fg=typer.colors.GREEN)

        if not created:
            typer.echo("Nothing to create (use --force to overwrite).")
            raise typer.Exit(code=1)

        typer.echo("\nNext steps:")
        typer.echo(f"  1. Edit {corti_toml} — fill in API keys (see comments inside)")
        root_flag = f" --root {resolved}" if root else ""
        typer.echo(f"  2. Run: corti server start{root_flag}")
