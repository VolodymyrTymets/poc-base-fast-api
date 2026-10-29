# ADR-0007 — ruff, mypy (strict) and pytest as the quality tools

- **Date:** 2026-10-29
- **Status:** accepted
- **Deciders:** volodymyr
- **Ticket:** POC-1.1
- **Supersedes:** Node ADR-0007 (Oxlint replaces ESLint as the linter). uv itself is ADR-0001; the pinned Python is ADR-0002. Scope doc task 1.4.

## Context
The repo has no lint, type-check or test tool yet; the command map in `CLAUDE.md` says `none` for all three. Rule B1 needs real commands to gate work on.

## Decision
- **ruff** for lint and format, with rule families `B`, `S`, `ASYNC` and `T20` on top of the defaults. Formatting is checked, not only applied.
- **mypy** in strict mode as the type check. It becomes a `typecheck` row in the command map, and so a gate.
- **pytest** with `pytest-asyncio` for tests, and coverage as a diagnostic only.
- All are development dependencies, added in task 1.4. This ADR adds none (rule C2).

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| black + flake8 + pylint | three tools and three configs where ruff covers lint and format |
| pyright | mypy is what the scope doc and the stack rules assume |
| unittest | less expressive fixtures; the stack rules are written for pytest |

## Consequences
- Positive: fast single-binary lint and format; strict typing from the first line of code.
- Accepted cost: mypy strict is demanding on third-party stubs; any `type: ignore` still needs a human-approved `WHY:` (rule B3).
- Follow-ups: task 1.4 installs the tools and fills the command map, the `allow` list in `.claude/settings.json` and CI (task 11.4).

## Revisit when
A faster type checker reaches parity on strict async code.
