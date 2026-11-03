# ADR-0020 — A `cli.py` module for project commands

- **Date:** 2026-11-03
- **Status:** accepted
- **Deciders:** volodymyr
- **Ticket:** POC-4.1
- **Supersedes:** nothing. It adds one file to the structure of ADR-0011 (rule 2: a new top-level module needs an ADR).

## Context
Task 4.1 needs a command that exports `openapi.json`. It must build the whole app, which imports every router, and only `main.py` may do that (ADR-0011).
`core/` imports no layer, so the command cannot live there. Leaving it in `main.py` mixed the app with command-line code.

## Decision
- `app/cli.py` holds commands that need the whole app. Today: `uv run python -m app.cli --export-openapi [--check] [--path FILE]`.
- It may import `app.main`, `app.config` and `app.core`. Nothing in `app/` imports `cli`.
- `main.py` stays the app only: `create_app()` and `run()`. Pure helpers (`render`, `is_current`) stay in `core/openapi.py`.
- `seeds` keeps its own `python -m app.seeds` (task 5.1).

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| Keep it in `main.py` | the app and a command-line parser in one file |
| Put it in `core/` | `core` would import `app.main` and so every router, against ADR-0011 rule 4 |
| A console script in `pyproject.toml` | an ask-first file and a new script name for a developer-only command |

## Consequences
- Positive: `main.py` is small again; the next command has a home.
- Accepted cost: one more top-level file.

## Revisit when
There are enough commands to want subcommands (then a `cli/` package, with its own ADR).
