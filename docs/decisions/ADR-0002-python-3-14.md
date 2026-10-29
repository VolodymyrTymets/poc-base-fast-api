# ADR-0002 — Pin Python 3.14

- **Date:** 2026-10-29
- **Status:** accepted
- **Deciders:** volodymyr
- **Ticket:** POC-0

## Context
`uv init` generated a 3.13 pin. The scope doc assumes 3.12 (task 1.3, `python:3.12-slim`). On 2026-10-29 the latest stable
CPython is 3.14 (3.15 is a release candidate only).

## Decision
`.python-version` is `3.14` and `requires-python` is `>=3.14`. Docker images and CI use the same minor version. Where the
scope doc says 3.12, this decision supersedes it.

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| 3.12 (scope doc) | older than the latest stable; no stated reason to stay |
| 3.13 (uv init default) | same |
| 3.15 | release candidate, not stable |

## Consequences
- Positive: newest stable language and typing features.
- Accepted cost: every dependency added later must support 3.14; a missing wheel is a blocker to report, not to work around.
- Follow-ups: raise the pin to 3.15 in its own PR once it is stable and the dependencies support it.

## Revisit when
3.15 is released, or a required dependency has no 3.14 support.
