# POC-4.1 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     Approved-by: <name> · <date> -->
Approved-by: volodymyr · 2026-11-03

Pattern followed: `app/main.py` (health `APIRouter(prefix=API_PREFIX)` + `include_router`) and `app/core/*.py` (one module per concern); the
`python -m` entry follows the `python -m app.seeds` style of ADR-0011, with the wiring in `main.py`. Rules: `.claude/rules/project-structure.md` (routers: no logic, schemas not ORM, only `main.py` imports routers).
Layer files exist as docstring-only, so this fills them rather than inventing a pattern; no ADR needed (ADR-0003 already decides the contract and the stale test).

## Contract changes
- boundary: additive. `/api/v1/health` unchanged; no new paths (tags only). New committed contract file `openapi.json`.
- data: none.
- generated output: `openapi.json` at the repo root, by `uv run python -m app.main --export-openapi`; never hand-edited.

## Requirements (ordered; branch `feat/POC-4.1-router-layout`, one draft PR, one commit each)

### R1 — Feature routers included under /api/v1 (S)
- files: `app/routers/{account,account_profile,account_role,auth,files,notifier}.py` (change: each defines `router = APIRouter(prefix=..., tags=[...])`, keeps its docstring),
  `app/main.py` (change: `TAGS` metadata passed as `openapi_tags`, `api.include_router(...)` for each router; `notifier` also gets an empty `router` with its tag (decided: AC1 and AC2 hold for all six); health stays in `main.py`).
- layer: routers, plus the app composition in `main.py`.
- test: `tests/unit/test_routers_layout.py` — every module in `app.routers` exposes `router` with exactly one tag equal to its module name; `create_app()`'s `openapi_tags` lists them. No HTTP call here: health stays covered by `tests/e2e/test_health.py`.
- executed how: `uv run poc-base-fast-api`, then `curl localhost:3001/openapi.json` (tags present) and `curl localhost:3001/api/v1/health`; `/docs` opened and checked.
- risk: low. Empty routers add no paths (A3), verified by the openapi call.

### R2 — OpenAPI export command and committed `openapi.json` (M)
- files: `app/core/openapi.py` (new, pure: `render(app: FastAPI) -> str` with sorted keys, indent 2, trailing newline; `is_current(app, path: Path) -> bool`; imports nothing from `app.main` or `routers`),
  `app/main.py` (change: `export_openapi(path=OPENAPI_PATH, check=False) -> int` builds `create_app(Settings())` and writes or checks; an `if __name__ == "__main__"` entry taking `--export-openapi [--check]`; wiring is allowed here),
  `openapi.json` (new, generated). Command: `uv run python -m app.main --export-openapi` (and `--check`). No new top-level module, so no ADR (project-structure 4 and 7 hold).
- layer: core (pure helper), main (wiring), generated file at root.
- test: `tests/unit/test_openapi_export.py` — render is deterministic (twice equal); `export_openapi(tmp_path/...)` writes what `render` returns; `--check` returns 1 against a modified temp copy and 0 against a current one; the spec is identical for two different `Settings`.
- executed how: `uv run python -m app.main --export-openapi` (second run leaves `git diff openapi.json` empty), `--check` exit 0; exit 1 shown against a temp copy via the path argument, never by editing the root file.
- risk: `python -m app.main` loads `app.main` as `__main__` too; harmless because only `export_openapi` runs. Cheapest check: run it in R2 before writing the tests.

### R3 — Stale-spec and response-model guard tests (S)
- files: `tests/unit/test_openapi_stale.py` (new: committed `openapi.json` equals `render()`; failure message names `uv run python -m app.main --export-openapi`),
  `tests/unit/test_response_models.py` (new: for every `APIRoute`, `response_model` is set and no class in it is a `Base` subclass; a test-local route returning an ORM class proves the check fails).
- layer: tests (unit: no Docker, no network; the app is built with `Settings()` and no `DATABASE_URL`).
- test: the files themselves. Failing-then-passing evidence for AC4: add a throwaway route, show the stale test red, regenerate, green, remove.
- executed how: `uv run pytest tests/unit/test_openapi_stale.py tests/unit/test_response_models.py -v` with the red/green sequence pasted.
- risk: none.

### R4 — Protected path, docs and command map (S)
- files: `.claude/rules/protected-paths.md` (change: add root-only `openapi.json` under "Never write (Python ecosystem)" with a one-line why pointing to ADR-0003, and fix the intro sentence that says no generated output exists yet; ask-first file), `CLAUDE.md` (change: map rows "openapi export" and "openapi check" with the `python -m app.main` commands; ask-first file),
  `docs/ARCHITECTURE.md` (change: repo layout and "Boundaries" now name routers, tags and `openapi.json`), `docs/RUNBOOK.md` (change: one "Contract" section with the command), `docs/api/ENDPOINTS.md` (change: replace "come in tasks 4.1" wording), `docs/features/POC-4.1/spec.md` (ACs ticked).
- layer: docs and agent config.
- test: grep that each named command and path exists; `uv run ruff check .`, `ruff format --check .`, `mypy`, `pytest tests/unit`, `pytest tests/e2e`.
- executed how: full gate output pasted.
- risk: CLAUDE.md edit changes the "only commands" map: flagged for the human reviewer.

## Docs to update in this PR
- [ ] spec.md ACs; ARCHITECTURE.md; RUNBOOK.md; ENDPOINTS.md wording; protected-paths.md; CLAUDE.md map row
- [ ] DOMAIN_GLOSSARY: no new term. ADR: none.

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| `python -m app.main` entry double-imports the module | surprising side effects | R2: run it first |
| Spec output differs by environment | flaky stale test | R2 test builds with two settings objects |
| `.claude/**` and `CLAUDE.md` writes prompt | slows R4 | expected (ask-first) |

## Assumptions
- A1 Health stays in `main.py`. A2 The spec does not depend on settings. A3 Tags are declared in `openapi_tags` so they appear while routers are empty.
- Work from `main` on a new branch; untracked scope doc and `.serena/` stay out of the PR. Estimate: R1 S, R2 M, R3 S, R4 S.
