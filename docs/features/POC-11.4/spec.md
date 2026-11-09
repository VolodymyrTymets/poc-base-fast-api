# POC-11.4 — CI workflow

## Problem
Nothing runs the checks on a pull request. `.github/workflows/agent-checks.yml` only checks the PR body and silent bypasses; ruff, mypy, pytest, the stale `openapi.json` check and the image build run only on a developer's machine, so a red `main` is possible and the `Done` rule B1 is unenforced.

## Goal / business value
Goal 3 (test base): the real-database suite keeps working because every PR runs it. Goal 1: a fork inherits a working pipeline.

## Scope
- in: `.github/workflows/ci.yml` (own PR, rule T4): ruff, `ruff format --check`, mypy, stale `openapi.json` check, `uv build`, and the whole pytest suite on a Docker-capable runner (testcontainers Postgres and Redis, the image build tests); ADR-0032; RUNBOOK "Release" and ARCHITECTURE updates; spec ticks.
- **out (explicit):** the scope row's "web typecheck + build" (no `web/`, ADR-0010); any step that ships anything to an environment (none is defined, rule C5); required-status-check and branch-protection settings (a repo admin sets them in GitHub; the PR body asks); changing `agent-checks.yml`; coverage upload or badges; caching the Docker layers beyond the runner default; a matrix of Python versions (3.14 only, ADR-0002).

## Acceptance criteria
- [ ] AC1 Given a clean PR, when CI runs, then every job is green (evidence: the run of the PR itself).
- [ ] AC2 Given a PR that breaks one test, then the test job is red and names the test (evidence: a throwaway draft PR, closed and its branch deleted afterwards).
- [ ] AC3 Given a PR that changes a route without regenerating `openapi.json`, then the static job is red at the openapi step; given lint, format or type errors, red at that step.
- [ ] AC4 CI installs with `uv sync --locked` (a stale `uv.lock` fails it), uses the Python of `.python-version`, and the uv version equals the one the Dockerfile pins.
- [ ] AC5 The suite needs no secret and no `.env`: no repository secret is read, `permissions` is `contents: read`, and the run is the same with no `.env.test`.
- [ ] AC6 A new push to the same PR cancels the older run; each job has a timeout.
- [ ] AC7 `agent-checks.yml` is untouched and still runs beside it.

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| Docker unavailable on the runner | the db tests fail with their Docker message, never skip (rule P8, B3) | existing fixtures |
| `tests/e2e/test_docker_image.py` is slow (two image builds) | runs in its own job so the quick feedback jobs are not held up | assumption A2 |
| A fork's PR | runs with the read-only token; nothing needs a secret | AC5 |
| `uv.lock` out of date | `uv sync --locked` fails the job | AC4 |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| A1 | Triggers | `pull_request` and `push` to `main` | no |
| A2 | Jobs | `static` (ruff, format, mypy, openapi, build), `tests` (`pytest -m "not e2e"`, Postgres), `e2e` (`pytest tests/e2e`, Docker image build and worker with Redis), three parallel jobs | confirm |
| A3 | Action versions | pinned to a major tag (`actions/checkout@v4`, `astral-sh/setup-uv`), verified against their docs before use; not pinned to a commit SHA | yes, confirm (SHA pinning is stricter) |
| A4 | Make the jobs required checks | a repo admin does it in GitHub settings; I only name the check names in the PR body | yes |
| A5 | The red-PR evidence (AC2) | a throwaway draft PR from a scratch branch with one deliberately failing assertion, closed unmerged and the branch deleted | yes, confirm |
