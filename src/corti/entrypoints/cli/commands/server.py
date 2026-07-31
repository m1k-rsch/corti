"""``corti server`` subcommand group.

Provides ``corti server start`` to run the HTTP API via uvicorn. CLI
parses arguments, configures structured logging, then hands off to
uvicorn pointing at :func:`corti.entrypoints.api.app.create_app` as a
factory.
"""

from __future__ import annotations

import logging
import os
import sys

import typer
import uvicorn

from corti.config.settings import resolve_root

app = typer.Typer(
    name="server",
    help="Run / manage the HTTP API server",
    no_args_is_help=True,
)


@app.command("start")
def start(
    host: str | None = typer.Option(
        None,
        "--host",
        help="Bind host (env: CORTI_API__HOST, default: 127.0.0.1)",
    ),
    port: int | None = typer.Option(
        None,
        "--port",
        help="Bind port (env: CORTI_API__PORT, default: 5473)",
    ),
    root: str | None = typer.Option(
        None,
        "--root",
        help="Memory root directory (env: CORTI_ROOT, default: ~/.corti)",
    ),
    reload: bool = typer.Option(
        False,
        "--reload",
        help="Reload on source changes (development)",
    ),
    log_level: str | None = typer.Option(
        None,
        "--log-level",
        help="Log level (env: CORTI_LOG_LEVEL, default: INFO)",
    ),
) -> None:
    """Start the HTTP API server."""
    if root:
        os.environ["CORTI_ROOT"] = root

    resolved_root = resolve_root(root)
    corti_toml = resolved_root / "corti.toml"
    if not corti_toml.is_file():
        typer.secho(
            f"Error: {corti_toml} not found.\n"
            f"Run `corti init` first to create configuration files.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    from corti.config import load_settings

    settings = load_settings()

    host_resolved = host or settings.api.host
    port_resolved = port if port is not None else settings.api.port
    log_level_resolved = (log_level or os.getenv("CORTI_LOG_LEVEL", "INFO")).upper()

    from corti.core.observability.logging import configure_logging

    configure_logging(level=log_level_resolved)

    bootstrap_logger = logging.getLogger("corti.cli.server")
    bootstrap_logger.info("starting corti on %s:%d", host_resolved, port_resolved)
    if host_resolved == "0.0.0.0":
        bootstrap_logger.warning(
            "binding to 0.0.0.0 exposes the API on all interfaces; Corti "
            "ships no built-in auth — see SECURITY.md"
        )

    try:
        uvicorn.run(
            "corti.entrypoints.api.app:create_app",
            host=host_resolved,
            port=port_resolved,
            reload=reload,
            factory=True,
            log_level=log_level_resolved.lower(),
            log_config=None,
        )
    except KeyboardInterrupt:
        bootstrap_logger.info("interrupted; shutting down")
    except (OSError, RuntimeError) as exc:
        bootstrap_logger.error("startup failed: %s", exc)
        sys.exit(1)
