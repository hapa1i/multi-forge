# Contributing to Multi-Forge

Thanks for your interest in contributing to Multi-Forge!

## Quick Start

**Prerequisites:** Python 3.11–3.13 and [uv](https://docs.astral.sh/uv/).

```bash
git clone <repo-url>
cd multi-forge
uv sync
pre-commit install
```

Run tests before submitting:

```bash
make test-unit        # Fast unit tests (~30s)
make pre-commit       # All hooks: ruff, black, isort, mypy, pyright, mdformat
```

## Submitting Changes

1. Branch from `main`
2. Make your changes with tests
3. Run `make test-unit` and `make pre-commit`
4. Open a PR targeting `main`

## Developer Guide

The full developer guide lives in [`docs/developer/`](docs/developer/):

- [Developer README](docs/developer/README.md) — setup, testing, architecture, common tasks
- [Coding Standards](docs/developer/coding-standards.md) — Python conventions, type safety, comments
- [Testing Guidelines](docs/developer/testing-guidelines.md) — test organization, fixtures, Docker
- [Documentation Guidelines](docs/developer/documentation-guidelines.md) — doc structure, writing style
- [Work Board Contract](docs/developer/work-board-contract.md) — board lanes, checklists, closeout

## Reporting Issues

- Use GitHub Issues for bug reports and feature requests
- Include reproduction steps and expected vs actual behavior
- For security issues, email the maintainers directly (do not open a public issue)

## License

By contributing, you agree that your contributions will be licensed under the [Apache 2.0 License](LICENSE).
