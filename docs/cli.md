# CLI

The `cortistrate` command-line entry point covers **setup and operations** —
generate starter config files (`init`), run the HTTP API server (`server
start`), inspect effective config (`config show`), and operate the
md → Postgres index queue (`cascade`). Hot-path
business (`/add` `/flush` `/search` `/get`) is the **HTTP API**, not the
CLI.

CLI commands run **in-process** — they call into the `service/` /
infrastructure layers directly rather than the HTTP loopback.

## Installation

The script is exposed via `pyproject.toml`:

```toml
[project.scripts]
cortistrate = "cortistrate.entrypoints.cli.main:app"
```

After `uv sync` (or `pip install -e .`) the `cortistrate` command resolves
to [`src/cortistrate/entrypoints/cli/main.py`](../src/cortistrate/entrypoints/cli/main.py),
a [Typer](https://typer.tiangolo.com/) app.

## Subcommand layout

```
cortistrate
├── init [--root PATH] [--force] [--print]   Generate starter config files (cortistrate.toml + ome.toml)
├── config
│   └── show [--root PATH]          Show effective configuration
├── server
│   └── start [--host] [--port] [--root] [--reload] [--log-level]   Start the HTTP API server (uvicorn)
├── cascade [--root PATH]           Inspect / operate the md → Postgres sync queue
│   ├── status                      Queue / LSN summary
│   ├── sync [PATH]                 Drain the queue now (optional PATH force-enqueues)
│   └── fix [--apply]               List failed rows / re-enqueue retryable ones
└── integrations                   Install Cortistrate into third-party tools
    ├── install [hermes] [--source PATH] [--force]
    └── uninstall [hermes] [--source PATH] [--force] [--yes]
```

Each subcommand lives in its own module under
[`entrypoints/cli/commands/`](../src/cortistrate/entrypoints/cli/commands/) and is
registered in `cli/main.py`. The CLI is intentionally small — hot-path
business (`/add` `/flush` `/search` `/get`) is the **HTTP API**, not the
CLI; the CLI covers setup (`init`), running the server, index ops
(`cascade`), and external-tool install (`integrations`). There is no
`reindex` command — rebuild by deleting `<root>/.index/postgres` and
restarting, or run `cortistrate cascade sync`.

## `cortistrate integrations`

Install Cortistrate integrations into third-party tools. Currently ships the
Hermes Agent memory-provider plugin — see
[hermes-integration.md](hermes-integration.md) for the full walkthrough.

```bash
cortistrate integrations install hermes [--source PATH] [--force]
cortistrate integrations uninstall hermes [--source PATH] [--force] [--yes]
```

`install` copies the bundle at `integrations/hermes/` into
`$HERMES_HOME/plugins/cortistrate/` so Hermes discovers it. The bundle source
resolves in this order: `CORTISTRATE_HERMES_PLUGIN_SOURCE` env → `--source`
flag → repo-root walk-up from `cortistrate.__file__` (covers editable/dev
installs). An existing directory is preserved (use `--force` to overwrite).
`uninstall` removes the directory only if it contains this
bundle (`--force` skips the ownership check; `--source` overrides the
expected path). `~/.cortistrate` memory data is never touched.

## `cortistrate server start`

Wraps `uvicorn` to launch the FastAPI app from
[`entrypoints/api/app.py`](../src/cortistrate/entrypoints/api/app.py)
in *factory* mode.

```bash
cortistrate server start \
    --host 127.0.0.1 \
    --port 8000 \
    --log-level info \
    --root ~/.cortistrate
```

| Flag | Env var | Default |
|---|---|---|
| `--host` | `CORTISTRATE_API__HOST` | `127.0.0.1` (loopback only; binding `0.0.0.0` logs a warning — Cortistrate ships no auth) |
| `--port` | `CORTISTRATE_API__PORT` | `8000` |
| `--log-level` | `CORTISTRATE_LOG_LEVEL` | `INFO` |
| `--root` | `CORTISTRATE_ROOT` | `~/.cortistrate` |
| `--reload` | — | off (use in development) |

Lifespan startup wires the storage backends (SQLite engine + Postgres
connection) on app boot; see
[`entrypoints/api/lifespans/`](../src/cortistrate/entrypoints/api/lifespans/).

## Configuration via env vars

Both CLI and HTTP server read configuration from `pydantic-settings`:

| Env var | Settings field |
|---|---|
| `CORTISTRATE_ROOT` | memory-root path (default `~/.cortistrate`) |
| `CORTISTRATE_MEMORY__TIMEZONE` | `Settings.memory.timezone` (e.g. `Asia/Shanghai`) |
| `CORTISTRATE_SQLITE__BUSY_TIMEOUT_MS` | `Settings.sqlite.busy_timeout_ms` |
| `CORTISTRATE_POSTGRES__READ_CONSISTENCY_SECONDS` | `Settings.postgres.read_consistency_seconds` |

Pattern: `CORTISTRATE_<SECTION>__<KEY>` (double underscore = nesting). See
[`config/settings.py`](../src/cortistrate/config/settings.py).

## Logging

`configure_logging` runs at CLI startup and configures `structlog` with
the resolved log level. All in-process logs (CLI command bodies +
service / infra layers) flow through the same handler.

```bash
cortistrate server start --log-level debug   # see all sql / postgres traffic
```

## API ↔ CLI division of labour

| Responsibility | API | CLI |
|---|---|---|
| Hot-path business (`/add` `/flush` `/search` `/get`) | ✅ | — (HTTP only) |
| Setup (generate config files) | — | `cortistrate init` |
| Inspect effective config | — | `cortistrate config show` |
| Run the server | — | `cortistrate server start` |
| Index ops (drain / inspect / fix the cascade queue) | — | `cortistrate cascade {status,sync,fix}` |
| Health probe | `GET /health` | (use HTTP) |
| Metrics scrape | `GET /metrics` | (use HTTP) |

The CLI is the **shell-friendly** surface for ops + scripting; the
HTTP API is the **process-friendly** surface for clients (web UIs,
agents, automation).

## See also

- [architecture.md](architecture.md) — DDD layering between
  entrypoints / service / memory / infra
- [`entrypoints/cli/main.py`](../src/cortistrate/entrypoints/cli/main.py)
- [`entrypoints/cli/commands/server.py`](../src/cortistrate/entrypoints/cli/commands/server.py)
