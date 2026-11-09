# POC-11.4 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code. -->
Approved-by:

Pattern followed: `.github/workflows/agent-checks.yml` (job layout, `ubuntu-latest`, `permissions`, `actions/checkout@v4`), the command map in `CLAUDE.md` (every CI command is one of its rows, rule T1), `Dockerfile` for the pinned uv. No CI precedent for the Python gates exists. The shape is recorded in ADR-0032 (rule D1).

## Contract changes
- boundary: none; `openapi.json` must not change.
- config / dependencies / generated output: none; `uv.lock` untouched.
- CI: one new workflow file, an ask-first path (`.github/workflows/**`) and rule T4: its own PR, a human reviewer, hook confirmation when it asks.

## Requirements (branch `feat/POC-11.4-ci-workflow`, one draft PR, one commit each)

### R1 — `ci.yml` (M)
- first step (riskiest unknown): verify the action inputs with Context7 or the action's docs (D4): `astral-sh/setup-uv` (version input, cache, Python from `.python-version`), `actions/checkout`. Then `actionlint` if installed (otherwise the PR run is the check).
- files: `.github/workflows/ci.yml`.
- shape: `on: pull_request` and `push: branches: [main]`; `permissions: contents: read`; `concurrency: group: ci-${{ github.ref }}`, `cancel-in-progress: true`; every job `runs-on: ubuntu-latest` with `timeout-minutes`.
  - `static`: `uv sync --locked`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run python -m app.cli --export-openapi --check`, `uv build`.
  - `tests`: `uv run pytest -m "not e2e"` (the unit tier and the integration tiers; testcontainers starts `postgis/postgis:16-3.4` on the runner's Docker).
  - `e2e`: `uv run pytest tests/e2e` (shutdown, seeds, the arq worker with a Redis container, the image build tests).
  - uv version pinned to the one in the `Dockerfile` (`0.12.22`, one value per file; a comment names the other place).
- test: no pytest file: a workflow is not unit-testable here. Evidence is the runs below.
- executed how: push the branch; the draft PR's own run is AC1. AC3: a second throwaway push on the scratch branch that edits a route without regenerating `openapi.json`, and one with a lint error, each showing the red step. AC2: the throwaway failing-assertion PR (A5). All scratch PRs are closed unmerged and their branches deleted; paste the run URLs.

### R2 — docs and ADR (S)
- files: `docs/decisions/ADR-0032-ci-workflow.md` (three jobs and why, Docker on the runner, pinned uv, no secrets, no web step, required checks left to an admin), `docs/RUNBOOK.md` ("Release": CI exists, how to run each job's commands locally, what a red job means), `docs/ARCHITECTURE.md` (the `.github/` row, Decided bullet), `docs/features/POC-11.4/spec.md` ACs ticked.
- Not edited without OK (ask-first): `CLAUDE.md` (no new command row is needed).

## Done check (rule B1)
`uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest -m "not db and not redis"`, `uv run python -m app.cli --export-openapi --check`, `uv build` locally, then the CI runs named above.

## Docs to update in this PR
- [ ] docs/features/POC-11.4/spec.md (ACs)
- [ ] docs/ARCHITECTURE.md, docs/RUNBOOK.md, ADR-0032
- [ ] docs/DOMAIN_GLOSSARY.md: none

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| Python 3.14 or a wheel (asyncpg, argon2-cffi) fails on the runner | every job red | first push runs `static` alone; watch it before adding more |
| the image build test or the worker test is slow or flaky on a shared runner | a red `e2e` that is not a bug | one rerun to tell; a flaky test is fixed or quarantined with a ticket (B3), never retried until green |
| host-gateway networking differs on the runner (`host.docker.internal`) | image test fails | its first run; ADR-0030 says it works on Linux |
| a scratch PR leaves clutter | none | closed and deleted in the same session |

## Assumptions
- A1-A5 of the spec; whoever writes `Approved-by:` also confirms A2 (three jobs), A3 (major-tag pins) and A5 (the throwaway failing PR).

## Estimate
R1 M · R2 S
