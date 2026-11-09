# ADR-0032 — CI: three parallel jobs, Docker on the runner, no secrets

- **Date:** 2026-11-09
- **Status:** accepted
- **Deciders:** Volodymyr
- **Ticket:** POC-11.4
- **Supersedes:** nothing. It adds a workflow beside `agent-checks.yml`, which stays as it is.

## Context
Until now ruff, mypy, pytest, the `openapi.json` check and the image build ran only on a developer's machine (rule B1 had no enforcement). The Node base's CI also ran a web typecheck and build; this repo has no `web/` (ADR-0010).

## Decision
- One workflow, `.github/workflows/ci.yml`, on `pull_request` and on `push` to `main`, with `permissions: contents: read`, a `concurrency` group that cancels an older run of the same ref, and a `timeout-minutes` on each job.
- Three jobs run in parallel on `ubuntu-latest`, each doing `uv sync --locked` first:
  - `static` ("lint, types, contract, build"): `ruff check`, `ruff format --check`, `mypy`, `python -m app.cli --export-openapi --check`, `uv build`.
  - `tests` ("unit and integration (real Postgres)"): `pytest -m "not e2e"`. testcontainers starts `postgis/postgis:16-3.4` on the runner's Docker (rule P8, ADR-0006); there is no service container and no `TEST_DATABASE_URL`.
  - `e2e` ("e2e (processes, Redis, image builds)"): `pytest tests/e2e`, which holds the shutdown, seed and worker tests (a Redis container) and the two image builds of ADR-0030. It has its own job because the image builds make it the slowest, so the other two report first.
- Every command is a row of the command map in `CLAUDE.md` (rule T1). The suite reads no secret and no `.env`.
- uv is pinned to `0.12.22`, the version the `Dockerfile` copies, in one `UV_VERSION` variable with a comment naming the other place. Python comes from `.python-version` (3.14); uv downloads it. A stale `uv.lock` fails `uv sync --locked`.
- Actions: `actions/checkout@v5` by major tag, as `agent-checks.yml` does with v4; `astral-sh/setup-uv` by commit SHA with its version in a comment, because its documentation pins it that way and publishes no floating major tag.
- No web step (no `web/`), and nothing here ships to an environment (none is defined, rule C5).
- Making the three jobs required checks is a repository setting an admin changes in GitHub; the check names are the job names above.

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| One job running everything | the slow image builds would hold up lint and unit feedback, and a red job would not say which tier broke |
| A Postgres `services:` container instead of testcontainers | two ways to get a database; the fixtures already handle Docker and fail loudly (rule P8) |
| `-m "not db and not redis"` in CI | that skips the real-database tests, the point of goal 3 |
| A Python version matrix | the repo pins 3.14 (ADR-0002) |
| Rerun failed jobs automatically | rule B3: a flaky test is fixed or quarantined with a ticket |

## Consequences
- Measured on the first run of the PR: `static` 19 s, `tests` about 1 min, `e2e` about 1 min 40 s (cold runner, uv cache empty).
- Each tier goes red on its own: a failing test reddens `tests` and names the test; a lint error, a format or type error or a stale `openapi.json` reddens `static` at that step.
- The runner label `ubuntu-latest` will move to a newer Ubuntu (GitHub announced it); the Docker-based tests would show it first.

## Revisit when
A `web/` returns, an environment is defined (a separate workflow, rule C5), or a job passes about 10 minutes.
