# Acknowledgments

[Home](README.md) > [Docs](docs/index.md) > Acknowledgments

Thanks to the following projects and communities.

---

## Upstream

### [EverOS](https://github.com/EverMind-AI/EverOS)

Cortistrate is a fork of EverOS by EverMind AI, licensed under Apache-2.0.
The core memory pipeline, Markdown-first storage model, and OME reflection
engine originate from the EverOS project.

The Hermes plugin (`integrations/hermes/`) is a rewrite of the EverOS Hermes
provider, redesigned for the new Cortistrate server. The system prompt
injection was rebuilt around the memory fragment model (title-based retrieval)
instead of full episode bodies.

The Claude Code plugin (`integrations/claude-code/`) is a rewrite of the
EverMem Cloud plugin (`use-cases/claude-code-plugin/`), which shipped inside
the EverOS repository under Apache-2.0. The entire API client layer, hook
scripts, and MCP server were rewritten to target the self-hosted Cortistrate
server (no auth, app/project/user scoping) instead of cloud endpoints
(Bearer auth, group scoping).

### [EverAlgo](https://github.com/EverMind-AI/EverAlgo)

The algorithm library (boundary detection, memory extraction, ranking,
clustering) is vendored under `src/everalgo/`. Licensed under the MIT License
by EverMind AI. The original license is preserved at `src/everalgo/LICENSE`.

---

## Inspiration & references

### [memsearch](https://github.com/zilliztech/memsearch)

Inspired our markdown-as-source-of-truth design and the SHA-256 +
file-watcher incremental sync model.

### [mem0](https://github.com/mem0ai/mem0)

Inspired the "one provider per file" flat adapter layout that Cortistrate uses
for `component/llm/` and `component/embedding/`.

### [Letta (MemGPT)](https://github.com/letta-ai/letta)

Inspired the multi-tier memory mapping (Core / Recall / Archival) that maps
naturally onto our MemCell / Episode / Archival pipeline.

### [MemOS](https://github.com/MemTensor/MemOS)

Provided a reference for memory taxonomy decisions (textual / parametric /
activation) and helped sharpen our scope choice to focus on textual memory.

### [Memos](https://github.com/usememos/memos)

A comprehensive open-source note-taking service whose plain-text-first
design philosophy reinforced our decision to keep markdown files as the
single source of truth.

### [Nemori](https://github.com/nemori-ai/nemori)

A self-organising long-term memory substrate for agentic LLM workflows that
provided valuable inspiration for our extraction pipeline.

---

## Open-source libraries

Cortistrate is built on top of excellent open-source libraries and frameworks:

### Core

- **[Python](https://www.python.org/)** — Programming language (3.12+)
- **[uv](https://github.com/astral-sh/uv)** — Fast Python package manager
- **[FastAPI](https://fastapi.tiangolo.com/)** — Modern async web framework (HTTP API)
- **[Pydantic](https://docs.pydantic.dev/)** — Data validation and settings

### Storage

- **[PostgreSQL + pgvector](https://github.com/pgvector/pgvector)** — Vector + BM25 + scalar database
- **[SQLite](https://sqlite.org/)** — Embedded relational database (state + audit log)

### Tooling

- **[Ruff](https://docs.astral.sh/ruff/)** — Lint + format
- **[import-linter](https://import-linter.readthedocs.io/)** — Layered architecture enforcement
- **[Hatchling](https://hatch.pypa.io/)** — Wheel build backend
- **[pytest](https://pytest.org/)** — Testing framework
- **[pre-commit](https://pre-commit.com/)** — Git hooks framework

### LLM & embedding providers

Cortistrate is provider-agnostic by design. Tested provider integrations include
OpenAI, Anthropic, Ollama, and SBERT. See [`component/llm/`](src/cortistrate/component/llm/)
and [`component/embedding/`](src/cortistrate/component/embedding/) for the
adapter layouts.

---

## Want to contribute?

Contributions are welcome! See the [Contributing Guide](CONTRIBUTING.md)
to get started.
