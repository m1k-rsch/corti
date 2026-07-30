"""``cortistrate config show`` — display effective configuration."""

from __future__ import annotations

import os

import typer

from cortistrate.config.settings import resolve_root

app = typer.Typer(
    name="config",
    help="Configuration management",
    no_args_is_help=True,
)

_SECRET_FIELDS = {"api_key"}

_SECTION_NAMES = (
    "memory",
    "api",
    "sqlite",
    "pg",
    "llm",
    "multimodal",
    "embedding",
    "rerank",
    "boundary_detection",
    "memorize",
    "clustering",
    "search",
    "knowledge",
)


def _mask(value: str) -> str:
    """Mask a secret value, keeping first/last 4 chars if long enough."""
    if len(value) <= 8:
        return "****"
    return value[:4] + "****" + value[-4:]


@app.command("show")
def show(
    root: str | None = typer.Option(
        None,
        "--root",
        help="Memory root directory",
    ),
) -> None:
    """Print the effective configuration."""
    if root:
        os.environ["CORTISTRATE_ROOT"] = root

    resolved = resolve_root(root)
    typer.echo(f"Root: {resolved}")
    typer.echo()

    cortistrate_toml = resolved / "cortistrate.toml"
    if cortistrate_toml.is_file():
        typer.echo(f"Config: {cortistrate_toml}")
    else:
        typer.echo("Config: (no cortistrate.toml found, using defaults)")

    ome_toml = resolved / "ome.toml"
    if ome_toml.is_file():
        typer.echo(f"Strategy: {ome_toml}")
    typer.echo()

    from cortistrate.config import load_settings

    load_settings.cache_clear()
    settings = load_settings()

    for section_name in _SECTION_NAMES:
        section = getattr(settings, section_name, None)
        if section is None:
            continue
        typer.secho(f"[{section_name}]", bold=True)
        for field_name, value in section.model_dump().items():
            display = str(value)
            if field_name in _SECRET_FIELDS and value:
                display = _mask(str(value))
            typer.echo(f"  {field_name} = {display}")
        typer.echo()
