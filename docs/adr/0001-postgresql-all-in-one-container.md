---
status: accepted
---

# Storage backend is PostgreSQL + pgvector, deployed in a single all-in-one Docker container

Corti deploys as a single Docker image bundling PostgreSQL 18 + pgvector and the corti server, with `supervisord` as PID 1. The app connects to PG over TCP `localhost:5432` (container loopback). All user data lives in a single host volume mounted at `~/.corti/` — markdown truth source, SQLite state, and PG index data — following 12-Factor App principles for code/config/data separation. The existing bare-Python deployment (`pip install` + external PG) remains fully supported via environment-variable configuration.

## Context

Corti's retrieval layer depends on **pgvector** — `vector(1024)` columns with HNSW cosine indexes (`vector_cosine_ops`, the `<=>` operator) plus `tsvector` generated columns with GIN indexes for BM25 recall. This is the core of the hybrid search path (BM25 + vector ANN) and cannot be trivially swapped.

The project's storage backend has already migrated once: **LanceDB → PostgreSQL 18.4 + pgvector**. LanceDB's Apache-Arrow / copy-on-write columnar format was a poor fit for the cascade daemon's continuous small-mutation write stream — versioned files accumulated without compaction, memory-mapped pages inflated RSS, and HNSW rebuilds spiked memory to 1.2–1.5 GB. After that migration, the SQL layer (DDL, repos, recallers, cascade handlers) is mature and stable on PG.

The remaining question is **deployment model**: how a personal / small-team user runs the tool without installing and configuring an external PostgreSQL server.

## Decision

1. **Keep PostgreSQL + pgvector** as the storage backend.
2. **Default deployment: single all-in-one Docker container** — PG + corti in one image, one `docker run` command.
3. **Base image: `pgvector/pgvector:pg18`** — official pgvector image shipping PostgreSQL 18 + pgvector extension pre-installed. Eliminates extension build steps and pins PG major version.
4. **Container-internal communication: TCP `localhost:5432`** — PG listens on `127.0.0.1` only; the app connects over TCP. Same interface as bare-Python mode, external PG, or remote PG — zero code branching.
5. **All user data in one directory**: `~/.corti/` mounted as a single host volume. Contains markdown files (truth source), SQLite state, PG index data, and user config.
6. **HTTP API default port: `5473`** — avoids collision with the crowded 8000-range used by many dev tools. Configurable via `CORTI_API__PORT` env var or `corti.toml`.
7. **Bring-your-own-PostgreSQL remains supported** — set `DB_HOST` environment variable to point at any external PG server. Same code, same binary.

## Why PostgreSQL over SQLite

A greenfield build targeting only personal single-user use would likely start with SQLite. We chose PostgreSQL deliberately, and are keeping it, for three reasons that compound as usage grows:

1. **Production-scale fit.** PG is built for concurrent, multi-user, larger-scale workloads. Standardizing on it once avoids a forced second migration later.
2. **Native vector quality.** pgvector's HNSW index and the `<=>` cosine operator deliver stronger, faster vector search than SQLite vector extensions (which lack HNSW and rely on IVF or brute-force scans). Hybrid recall (BM25 `ts_rank_cd` + ANN) is a first-class PG feature, not an afterthought.
3. **Scalability headroom.** Personal deployments already reach meaningful load — a single operator can run ~10 agent runtimes (3–4 frequently active). A small team can multiply that 10–100×. PG's connection pooling, concurrency, and indexing handle that headroom without rework.

## Why TCP localhost (not Unix socket) inside the container

- **Interface uniformity.** TCP `localhost:5432` works identically inside the container, on bare-metal with a local PG, and against a remote PG server. One connection code path, zero branching. Unix socket is container-internal only — switching to BYO-PG would change the connection mechanism.
- **Simplicity.** TCP is conceptually clear; Unix socket adds a path-format abstraction that complicates debugging and the `pool.py` interface.
- **Auth friction is a one-time cost.** Unix socket's "OS user = PG user" convenience is irrelevant inside a container (single effective user). The Docker entrypoint script creates PG users/passwords once during image build — the user never sees this.

## Data layout — single directory (`~/.corti/`)

All persistent data lives under one host directory, mounted into the container at `/home/app/.corti/`:

```
~/.corti/                           # Host volume (single mount point)
├── <app_id>/<project_id>/               # User-visible markdown (TRUTH SOURCE)
│   ├── users/<user_id>/
│   │   ├── user.md                     # Profile (single-file rewrite)
│   │   ├── episodes/                   # Daily-log append
│   │   ├── .atomic_facts/              # Hidden, framework-derived
│   │   └── .foresights/               # Hidden, framework-derived
│   └── agents/<agent_id>/
│       ├── .cases/
│       └── skills/
├── .index/                              # System-managed (rebuildable from markdown)
│   ├── sqlite/                        # system.db (state, cascade queue, audit)
│   │   ├── system.db
│   │   ├── ome.db
│   │   └── ome.aps.db
│   └── pg/                            # PG data directory (Docker only)
│       └── (PGDATA = /home/app/.corti/.index/pg)
├── corti.toml                     # User config overrides (loaded by Settings)
└── ome.toml                             # OME strategy overrides
```

**Why one directory works:**
- One `docker run` mount: `-v ~/.corti:/home/app/.corti`
- One backup target: `rsync ~/.corti/ backup/` captures everything
- Familiar pattern: like `~/.ssh/`, `~/.config/` — other apps do this

**Why the `.index/` subdirectory for system data:**
- The `.` prefix signals "don't touch" — users browsing their markdown won't accidentally modify PG binary data or SQLite internals
- Separates user-editable content (markdown) from system-managed binary data (PG, SQLite)
- The project already uses this convention — `.index/sqlite/` exists in bare-Python mode

**Permissions:** The Docker entrypoint runs `chown` on the mounted volume so that both the `postgres` user (for PG) and the app user (for markdown writes) have correct access. This requires the container entrypoint to run as root initially, then drop privileges for the app process — a standard pattern for single-container images.

## 12-Factor App alignment

| Factor | Implementation |
|---|---|
| **I. Codebase** | Baked into Docker image (immutable). `pip install corti` from the image. |
| **III. Config** | Environment variables (`CORTI_LLM__API_KEY`, etc.) for secrets. `corti.toml` in memory root for non-secret overrides. Both feed into `pydantic-settings`. |
| **IV. Backing services** | PG treated as attached resource. Connection via `DB_HOST` / `DB_PORT` env vars — no hardcoded connection string. Swap to external PG by changing one env var. |
| **V. Build/release/run** | Three stages: PyPI package (`pip install corti`), Docker image build (GHCR), `docker run`. |
| **VI. Processes** | `supervisord` manages PG + corti as equal child processes. Container restart = both restart together. |
| **VII. Port binding** | Only `:5473` exposed to host (HTTP API). PG listens on container loopback only (`127.0.0.1:5432`). No port conflict with host PG on `:5432`. |
| **VIII–IX. Concurrency / Disposability** | PG connection pool (`psycopg_pool.AsyncConnectionPool`) handles concurrent requests. Container is stateless — all state in the mounted volume. |

## Distribution channels

| Channel | User command | Target user |
|---|---|---|
| **PyPI** | `pip install corti` | Bare-Python deployment (BYO-PG, development) |
| **Docker Hub / GHCR** | `docker run -p 5473:5473 -v ~/.corti:/home/app/.corti corti/corti` | One-click deployment (personal / small team) |
| **CLI subcommand** | `corti docker start` | Bridges PyPI install → Docker launch (auto-detects Docker, pulls image, mounts volumes) |

## Considered options (and why rejected)

- **PGlite (WASM-compiled PG).** Attempted on 2026-07-19 and **failed**: psycopg3 async pool segfaulted, asyncpg / psycopg2 failed, the single psycopg3 sync-over-TCP connection crashed on reconnect. Root cause was `@electric-sql/pglite-socket` instability. PGlite also carries a hidden Node.js dependency and lacks production-grade concurrency. **Rejected — unstable for this workload.**
- **SQLite + sqlite-vec.** True zero-dependency, but requires rewriting all DDL, repos, and recallers, and sacrifices HNSW for weaker IVF/brute-force vector search. The rewrite cost is not justified given PG already works. Retained as a possible future "embedded/personal-only" tier, not the default.
- **LanceDB (revert).** The prior backend; migrated away from because its copy-on-write columnar format is hostile to the cascade daemon's continuous small writes (memory spikes, disk bloat). **Rejected — known-bad fit.**
- **DuckDB.** Immature experimental vector support; no native full-text search. **Rejected.**
- **Docker Compose (two containers).** Viable, but adds inter-container networking, two volumes, and a compose file for no benefit — the app and DB never scale independently. Rejected in favor of the single all-in-one image.
- **Unix socket for container-internal PG.** Works fine (Docker has independent filesystem namespaces, sockets don't leak to host). But breaks interface uniformity — BYO-PG requires TCP. Rejected in favor of TCP localhost for simplicity.

## Consequences

- **The only host prerequisite is Docker.** This is a deliberate, accepted trade-off against the original "zero dependency" goal — Docker is a reasonable assumption for the target audience (AI-agent users, who already manage LLM runtimes and API keys).
- **PG and the app share a lifecycle.** Upgrading PG means rebuilding the image; a process supervisor owns graceful shutdown. Both are acceptable for a single-user / small-team tool.
- **No code change to the storage layer.** The existing `psycopg3` async pool, `pgvector` DDL, and recall SQL all remain as-is — the containerization is purely a deployment concern. The "bring-your-own-PG" path means the same binary runs against an external server when configured to.
- **Cross-machine topology caveat.** For multi-machine agent fleets, all agents must reach the single container's HTTP API (`0.0.0.0:5473`); the PG data lives on one host. Fine for personal / small-team use; would need rethinking for a large distributed fleet.
- **Backup is one directory.** `rsync ~/.corti/ backup/` captures markdown (truth source), SQLite (state), and PG (index). Everything is rebuildable from markdown alone, but a full backup avoids the cascade re-sync cost.
