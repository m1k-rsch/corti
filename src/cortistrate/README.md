# `cortistrate` package

Source layout for the `cortistrate` Python package. This README is a quick
orientation; full architectural detail lives elsewhere.

## Layout

```
cortistrate/
├── entrypoints/    Presentation: cli + api
├── service/        Application: use case orchestration
├── memory/         Domain: extract + search + cascade + prompt_slots + models
├── infra/          Infrastructure: persistence/{markdown, sqlite, pg}
├── component/      Cross-cutting providers: llm / embedding / config / utils
├── core/           Runtime base: observability / lifespan / context
└── config/         Data: Settings + default.toml + prompt_slots templates
```

Each subpackage has a top-level `__init__.py` describing its responsibility
and public API.

## Dependency rule

```
entrypoints → service → memory → infra
                          ↓
                    component / core / config
```

Single-direction; enforced by `import-linter` in CI.

## Further reading

- Architecture: [../../docs/architecture.md](../../docs/architecture.md)
- Coding rules (auto-loaded by Claude Code): [../../.claude/rules/](../../.claude/rules/)
