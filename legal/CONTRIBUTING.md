# Contributing to Corti

Thanks for your interest in contributing! This guide covers the basics.

## Development Setup

```bash
git clone https://github.com/m1k-rsch/corti.git
cd Corti
uv sync          # install deps + create .venv
make ci          # lint + test + integration
```

## Branch Strategy

`main` is the default and protected branch. Create scoped branches:

- `feat/*` — new features
- `fix/*` — bug fixes
- `docs/*` — documentation
- `ci/*` — CI/CD changes
- `refactor/*` — code refactoring

## Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add Postgres connection pooling
fix: resolve race condition in cascade watcher
docs: update install instructions
```

## CI Gates

All PRs must pass:

- `make lint` — ruff check + format check + import-linter
- `make test` — pytest unit tests
- `make check-cjk` — no CJK in non-test source

## Pull Requests

1. Fork the repo and create a branch from `main`
2. Make your changes, ensure `make ci` passes
3. Open a PR with a clear description
4. Link any related issues

## License

By contributing, you agree that your contributions will be licensed under the
Apache-2.0 license.
