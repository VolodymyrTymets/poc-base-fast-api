# POC-3.4 — Test layout by pyramid level, markers, AAA, mock audit

> Ticket IDs POC-3.4 (layout, markers, docs), POC-3.5 (AAA sweep) and POC-3.6 (mock and data gaps) confirmed by volodymyr, 2026-11-04. The rows still need adding to the scope doc.

## Problem
The suite (about 646 test functions, 40 files in `tests/unit`, 45 in `tests/e2e`) has two levels, but the course material (07-pytest) and the owner's
vocabulary have three: **unit**, **integration** (the API or a service on a real Postgres), **e2e** (the real app as a process, the way a client reaches it).
Today `tests/e2e/` holds almost only integration tests (19 `test_db_*`, 17 `test_http_*`, plus fixture self-tests); only `test_shutdown.py` (uvicorn as a
subprocess), `test_worker_arq.py` (the arq worker as a subprocess, real Redis) and `test_db_seed_entrypoints.py` (a project command as a subprocess) are e2e in the deck's sense. DB-level and HTTP-level tests share one
folder, no custom marker exists, so `-m "not e2e"` style selection is impossible, Arrange-Act-Assert is not visible in the test bodies (one `# Arrange/Act/Assert`
label in the whole suite), and the mock/factory practice has not been checked against the deck.

## Goal / business value
Goal 3 (Test base): a real-database test setup that keeps working and is easy to extend. A fork can run the fast tier on every save and the slow tier before push.

## Scope
- in: rename the levels to `tests/unit`, `tests/integration/{db,http}`, `tests/e2e` (real processes only); register markers and apply them by folder;
  the AAA convention and a sweep that applies it; an audit of mocking, fakes and test data against the deck with the gaps fixed or listed; rule, skill, RUNBOOK and
  command-map updates.
- **out (explicit):** Playwright or any browser test (no `web/`, rule P3, and a new dependency, rule C2); `respx` (the app makes no outbound HTTP, `grep` of `app/`
  finds no httpx/requests/aiohttp client); `pytest-mock`, `polyfactory`, `pytest-xdist` (no need shown; each is a dev dependency to approve separately); a CI workflow
  (task 11.4, rule T4); changing what any test asserts (rule B3); `--cov-fail-under` (coverage stays a diagnostic, `testing.md` 7); renaming test files or functions.

## Acceptance criteria
- [ ] AC1 `tests/integration/db/`, `tests/integration/http/` and `tests/e2e/` exist; `tests/e2e/` holds only the tests that start a real process; every file moved with `git mv`.
- [ ] AC2 The same tests run before and after: the collected count per level is recorded in the PR (nothing lost, nothing renamed), and `uv run pytest` is green.
- [ ] AC3 `pyproject.toml` registers `unit`, `integration`, `e2e`, `db`, `http`, `redis`; `--strict-markers` stays; a hook in `tests/conftest.py` marks each item from its path;
      a unit test fails when a collected item lacks exactly one level marker.
- [ ] AC4 `pytest -m unit`, `-m "not e2e"`, `-m integration`, `-m "integration and http"`, `-m db`, `-m redis` each select what the name says (counts shown).
- [ ] AC5 `testing-python.md`, `testing.md` rule 9 note, the `test-conventions` skill, RUNBOOK, ARCHITECTURE and the CLAUDE.md command map describe the new layout, markers and AAA shape.
- [ ] AC6 (PR 2) every test body has the AAA shape: one Act, blank-line separated blocks, section labels per the decided convention; multi-Act tests are split or justified.
- [ ] AC7 (PR 3) the mock audit table in `plan.md` has each row either fixed or filed; shared builders replace the 15 copies of `make_app` and 7 of `unique_email`.

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| Two files with one basename after the split | collection must still work: file names stay unique across all folders (no `__init__.py`) | assumption A3 |
| `test_health.py`, `test_body_limit.py` use `TestClient`, need no database | `integration/http`, marked `http` only (they exercise the app over HTTP; no Docker) | assumption A4 |
| `test_db_session.py` mocks the engine with `create_autospec` and needs no database | moves to `unit` in PR 3 audit; until then stays in `integration/db` | audit row 3 |
| `redis_settings` tests (`test_worker_arq.py`) need Redis, not Postgres | `e2e` + `redis` markers | A5 |
| A developer without Docker runs `pytest -m unit` | passes with no Docker (already true: rule 1 of testing-python) | existing |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| Q1 | Ticket IDs: is this POC-3.4 (PR 1), 3.5 (AAA sweep), 3.6 (mock/factory gaps)? One PR = one requirement (A4), and the scope doc is the only list | yes, add the three rows to the scope doc | **Answered 2026-11-04:** POC-3.4 to 3.6 confirmed | no |
| Q2 | AAA style: `# Arrange` / `# Act` / `# Assert` labels as in the deck, or blank-line separation only (what `testing.md` 9 asks, and rule D6 says comments explain why)? | labels, one word each, on every test with more than one statement; they are section markers, not explanations | **Answered 2026-11-04:** use labels | no |
| Q3 | Mark by folder through one collection hook, or an explicit `pytestmark` in each of about 90 files? | hook: one place, cannot be forgotten, the unit test guards it | no |
