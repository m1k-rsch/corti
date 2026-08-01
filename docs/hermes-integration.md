# Hermes Agent Integration

Wire [Hermes Agent](https://github.com/NousResearch/hermes-agent) to an
Corti server as its long-term, cross-session memory backend — durable
markdown memory, semantic + lexical recall, and offline consolidation,
with no `hermes-agent` PR required.

The integration ships **inside the Corti repo** as a Hermes
`MemoryProvider` plugin bundle at
[`integrations/hermes/`](../src/integrations/hermes/). The
`corti integrations install hermes` command copies the bundle into
`~/.hermes/plugins/corti/`; Hermes discovers user-installed plugins and
loads them via the `MemoryProvider` subclass-fallback path.

## Prerequisites

- An Corti server you can reach (local or remote). For install +
  `corti server start`, see [README](../README.md).
- Hermes Agent installed (`hermes` on your `PATH`).
- For **OSS mode** (local Corti with self-supplied models): an
  OpenAI-protocol LLM, embedding, and (optionally) rerank endpoint —
  e.g. DeepInfra, OpenRouter, OpenAI, Together, or a local vLLM/Ollama
  exposing the OpenAI shape.

## Install

```bash
# from the Corti checkout (editable/dev install — the common case)
corti integrations install hermes

# or, for a non-editable install, point at the bundle explicitly:
corti integrations install hermes --source /path/to/Corti/integrations/hermes

# activate it in Hermes
hermes config set memory.provider corti
```

Verify Hermes discovered the plugin:

```bash
hermes memory status
# → Provider: corti  ·  Plugin: installed ✓  ·  Status: available ✓
#   Installed plugins: … corti (local) ← active
```

Then configure it with `hermes memory setup` (select `corti`) or by
editing `$HERMES_HOME/corti.json` directly (see [Config](#config)).

## Modes

| Mode | When | Config |
|---|---|---|
| `platform` | A vendor-hosted / remote Corti server | `api_url` only |
| `oss` (default) | Corti runs locally with your own LLM / embedding / rerank | `api_url` + `~/.corti/corti.toml` (the setup wizard writes it) |

`hermes memory setup` walks you through either mode. In OSS mode the
wizard writes `~/.corti/corti.toml` with `[llm]`, `[embedding]`, and
`[rerank]` blocks (chmod 600) — see
[configuration.md](configuration.md) for the full key reference. When
`agent_track_enabled` is set, it also seeds `~/.corti/ome.toml` to turn
on the agent-track OME strategies (`extract_agent_case`,
`extract_agent_skill`, `trigger_skill_clustering`).

## Config

Behavioral settings live in `$HERMES_HOME/corti.json`. Secrets belong in
`$HERMES_HOME/.env` (e.g. `CORTI_API_KEY`), not `corti.json`.

| Key | Default | Description |
|---|---|---|
| `api_url` | `http://127.0.0.1:8000` | Corti server URL |
| `mode` | `oss` | `platform` or `oss` |
| `user_id` | `hermes-user` | Corti user id to index your memories under. When unset, the gateway-native id (Telegram/Discord/Slack) flows through so the same human gets one merged store |
| `agent_id` | `hermes` | Corti agent id (agent-track attribution) |
| `app_id` | `default` | Corti app scope |
| `project_id` | `default` | Corti project scope |
| `agent_track_enabled` | `false` | Also write/search the agent track (cases + skills) |
| `api_key` | — | CLI-only; read by the `hermes corti` subcommands. The provider itself does not authenticate (Corti is loopback/no-auth by default) |

`app_id` / `project_id` must match `^[a-zA-Z0-9_.@+-]+$` (the server-side
`PathSafeId` charset) and reject `.` / `..`.

## How it works

### Write path (every turn → durable memory)

After each completed Hermes turn, `sync_turn` builds two `MessageItem`s
(user + assistant, Unix-ms timestamps) and `POST /api/v1/memory/add`s them
on a daemon thread. Corti buffers them per `session_id`; its boundary
detector decides when a segment is done, then the extractor (an LLM)
writes an **Episode** to markdown synchronously —
`~/.corti/.../users/<user_id>/episodes/episode-<date>.md`. At session end,
`on_session_end` calls `POST /memory/flush` to force extraction of any
pending buffer.

Markdown is the source of truth; SQLite (state) and Postgres
(vectors + BM25) are derived and rebuildable. See
[how-memory-works.md](how-memory-works.md).

### Recall path (every turn → relevant context injected)

Before each turn, `prefetch` fires a background `POST /memory/search`
(`include_profile=True`) and waits up to 1.5 s. The result — top episodes
(subject + truncated narrative) + nested atomic facts + a profile
one-liner, score-sorted — is injected into the agent's context for that
turn. If the server is slow, the result surfaces on the next turn
(mem0-style two-phase).

### Long-term, consolidating

Episodes persist across Hermes restarts and chats. The Offline Memory
Engine runs in the background: `extract_atomic_facts` (single-sentence
facts), `extract_user_profile` (an evolving `user.md`), and — opt-in,
weekly cron — `reflect_episodes`, which merges fragmented episodes about
the same topic into one narrative and soft-archives the originals. See
[reflection.md](reflection.md).

## Tools exposed to the agent

Beyond passive prefetch, the agent gets four tools:

| Tool | Maps to | Purpose |
|---|---|---|
| `corti_search` | `POST /memory/search` | Semantic + lexical hybrid recall |
| `corti_list` | `POST /memory/get` | Paginated browse of episodes / profile / cases / skills |
| `corti_add` | `POST /memory/add` + `/flush` | Buffer a fact and force extraction |
| `corti_flush` | `POST /memory/flush` | Force extraction of the current session buffer |

`corti_search` / `corti_list` take an `owner` (`user` | `agent`) to
select the user vs agent track, independent of `mode`.

## Hermes-side CLI

When `memory.provider` is `corti`, Hermes exposes `hermes corti …`:

```bash
hermes corti status                 # reachability + active config/scope + breaker state
hermes corti search "QUERY" [--top-k N] [--method hybrid|vector|keyword|agentic] [--owner user|agent]
hermes corti flush [--session-id ID]
hermes corti setup --mode oss --api-url ... --user-id ...   # non-interactive corti.json writer
```

`hermes corti setup` only manages `corti.json`; for full OSS setup
(including `~/.corti/corti.toml`) use `hermes memory setup`.

## Resilience

A circuit breaker trips after 5 consecutive transient failures (server
down, LLM/embedding 503) and pauses calls for 120 s. A down Corti server
never crashes Hermes or stalls the conversation — it degrades to built-in
`MEMORY.md`/`USER.md` until the server recovers. Client errors
(`INVALID_INPUT`, `NOT_FOUND`, …) do **not** trip the breaker.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `hermes memory status` shows `Status: not available` | `corti.json` missing or `api_url` empty — run `hermes memory setup` |
| `corti_search` returns 503 | The query-embedding step failed — check `~/.corti/corti.toml` `[embedding]` is reachable |
| Memories not appearing after `corti_add` | `corti_add` buffers + flushes; extraction runs on flush. If extraction fails, check the Corti server logs and the `[llm]` config |
| Recall misses a just-written episode | Postgres indexing is async (sub-second, up to ~10–15 s under load); retry, or `corti cascade sync` |
| `hermes corti …` command not found | The CLI is gated on `memory.provider == corti` — run `hermes config set memory.provider corti` |

## Uninstall

```bash
corti integrations uninstall hermes          # removes the plugin directory
# revert the provider if you no longer use it:
hermes config set memory.provider ''
```

`~/.corti` (your actual memory data) is preserved.

## See also

- [Integration bundle](../src/integrations/hermes/) — plugin bundle source (manifest: `plugin.yaml`)
- [how-memory-works.md](how-memory-works.md) — the write→index→read pipeline
- [api.md](api.md) — the Corti HTTP API v1 contract this plugin calls
- [configuration.md](configuration.md) — `corti.toml` / env-var reference
- [cli.md](cli.md) — the `corti` CLI, including `corti integrations`
