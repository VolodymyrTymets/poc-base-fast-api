# ADR-0001 — Use uv with the uv_build backend

- **Date:** 2026-10-29
- **Status:** accepted
- **Deciders:** volodymyr
- **Ticket:** POC-0

## Context
The repo was created with `uv init --package`: `pyproject.toml` declares `build-backend = "uv_build"`, a `src/` layout
and a `[project.scripts]` entry. The scope doc (task 1.3, 1.4) also assumes uv.

## Decision
`uv` is the only dependency manager and runner (rule T3): `uv sync`, `uv add`, `uv build`, `uv run`. `uv.lock` is committed
and never hand-edited. The build backend stays `uv_build`.

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| pip + `requirements.txt` | no lockfile, no interpreter management |
| poetry / pdm | not what the repo or the scope doc uses |

## Consequences
- Positive: one tool for interpreter, environment, lock and build; reproducible installs.
- Accepted cost: contributors need uv installed.
- Follow-ups: lint and test commands arrive in task 1.4 as dev dependency groups.

## Revisit when
A deployment target cannot run uv, or `uv_build` cannot build something the package needs (compiled extensions).
