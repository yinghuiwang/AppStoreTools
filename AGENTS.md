# Repository Guidelines

## Project Structure & Module Organization

This repository is a Python CLI package for App Store Connect automation. Source code lives in `src/asc/`, with Typer CLI wiring in `cli.py`, API access in `api.py`, configuration in `config.py`, and feature commands under `src/asc/commands/`. Template upload data lives in `src/asc/templates/`. Tests are in `tests/` and mirror feature areas with files such as `test_api.py`, `test_metadata.py`, and `test_build.py`. Example user data and screenshots are under `data/`; tutorials and architecture notes are in `docs/` and `ARCHITECTURE.md`.

## Build, Test, and Development Commands

Install the package for local development:

```bash
pip install -e ".[dev]"
```

Run the test suite:

```bash
pytest
```

Build distributable packages:

```bash
python -m build
```

Run the CLI locally after editable install:

```bash
asc --help
asc --app myapp upload --dry-run
```

Publishing is handled by `.github/workflows/publish.yml` when a `v*.*.*` tag is pushed.

## Coding Style & Naming Conventions

Use Python 3.9+ syntax and keep modules focused on one command or concern. Follow existing style: 4-space indentation, `from __future__ import annotations` in modules that already use it, snake_case functions and variables, PascalCase classes, and `test_*` test functions. Prefer small command handlers that delegate shared behavior to reusable core functions. Keep user-facing CLI text compatible with the existing Chinese/English i18n pattern in `src/asc/i18n.py`.

## Testing Guidelines

Tests use `pytest` and mocks for App Store Connect interactions by default. Add or update tests in `tests/` for any behavior change, especially command dispatch, config precedence, API retries, guard behavior, and upload validation. Use `tmp_path`, fixtures, and `unittest.mock` rather than real credentials or network calls. Live ASC tests must remain opt-in, for example via `ASC_TEST_LIVE=1`.

## Commit & Pull Request Guidelines

Recent commits use concise Conventional Commit-style messages, such as `feat(update): add --version and --branch options`, `fix(update): skip editable check...`, `test: add tests...`, and `docs: add...`. Follow that pattern.

Pull requests should include a clear summary, linked issue when applicable, test results (`pytest` output is sufficient), and screenshots or sample CLI output for user-visible command changes. Note any credential, App Store state, or CI implications.

## Security & Configuration Tips

Never commit real `.p8` keys, `.env` files, local profiles, or generated credentials. Local project config belongs in `.asc/config.toml`; reusable profiles and keys are stored under `~/.config/asc/`. Use dry-run commands before uploads that modify metadata, screenshots, IAP, or release state.
