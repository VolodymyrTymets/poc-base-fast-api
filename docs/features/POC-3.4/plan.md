# POC-3.4 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     Approved-by:  -->
Approved-by: Volodymyr· 2026-11-04

Pattern followed: the existing flat layout and naming of `tests/` (`.claude/rules/testing-python.md` rule 4, `tests/conftest.py` fixtures untouched) and the marker
mechanics of `--strict-markers` already in `pyproject.toml`. **No precedent for a collection hook or for a third level**; ADR-0029 records it (rule D1).
Scope of this PR: **POC-3.4 = R1 to R4 (layout, markers, docs)**. The AAA sweep (POC-3.5) and the mock/factory gaps (POC-3.6) are separate PRs (rule A4), outlined below.

## Target layout
```
tests/conftest.py, utils/        # unchanged, still at the root
tests/unit/                      # no Docker, DB, network, Redis, process        -> marker unit
tests/integration/db/            # services, models, seeds, migrations on a real Postgres -> integration + db
tests/integration/http/          # the app over ASGI/TestClient, endpoints        -> integration + http (+ db when it uses a database fixture)
tests/e2e/                       # the real app or worker as a process           -> e2e (+ redis for the worker)
```
Mapping of today's 45 e2e files: `test_db_*` (18, all but the next one), `test_test_database*` (4), `test_frozen_clock` -> `integration/db`; `test_http_*` (17), `test_health`,
`test_body_limit` -> `integration/http`; `test_shutdown`, `test_worker_arq` and `test_db_seed_entrypoints` (it runs `python -m app.seeds` as a child process) -> `tests/e2e`, the last one marked `e2e` + `db`.
Rule for ADR-0029: e2e = the test starts the app, the worker or a project command as its own process; in-process ASGI is integration. File names do not change (they stay unique across all folders,
there is still no `__init__.py`, so no import-mode change); dropping the `db_`/`http_` prefixes is a later, optional rename.

## Contract changes
- boundary: none. No route, `openapi.json` unchanged (stale test confirms).
- tooling surface: command `uv run pytest tests/e2e` no longer runs the integration tests. New command-map rows: `integration tests`, and `e2e` redefined. Anyone with the old
  command in muscle memory or an IDE run config gets 2 tests, not 226 (called out in the PR body).
- generated output: none.

## Requirements (ordered; branch `chore/POC-3.4-test-layout`, one draft PR, one commit each)

### R1 — Move the files by level (M)
- files: `git mv` of the 45 files as mapped above; `.claude/rules/routes-convention.md` glob `tests/e2e/test_http_*.py` -> `tests/integration/http/test_http_*.py` (ask-first, in R3's confirmation). Depth-dependent code found by grep: `REPO_ROOT = Path(__file__).resolve().parent.parent.parent` in `test_db_migrations.py` and `test_test_database.py` (both move one level deeper, so
  `.parent` x4, or better a shared `REPO_ROOT` from `tests/utils`); `test_worker_settings.py` passes `__file__` to a subprocess (stays in unit, unaffected); the docstring path in `test_initial_revision.py` is updated.
- layer: tests only.
- test: the suite itself. Before the move record `uv run pytest --collect-only -q | tail -3` (unit and e2e counts); after, the three folders must add up to the same total.
- executed how: `uv run pytest tests/unit`, `uv run pytest tests/integration`, `uv run pytest tests/e2e`, real output in the PR (needs Docker; Redis for the worker file).
- risk: a test that finds a file relative to its own path (see Risks).

### R2 — Register markers and apply them by path (S)
- files: `pyproject.toml` (ask-first file; `markers = [...]` with one line each: `unit` no external resource; `integration` real Postgres or the app in process;
  `e2e` the real app or worker as a process; `db` needs Postgres; `http` calls the app over HTTP; `redis` needs Redis); `-ra` added to `addopts`; `tests/conftest.py`
  (`pytest_collection_modifyitems`: level marker from the top folder, `db`/`http` from the second folder, plus `db` for any item that requests `db_session`, `db_engine`,
  `module_database_url` or `client`/`asgi_app` through `request.fixturenames`, `redis` for `redis_settings`/`redis_target`).
- layer: test infrastructure.
- test: `tests/unit/test_marker_assignment.py` — a plain unit test over a pure function `markers_for(path, fixturenames)` extracted to `tests/utils/markers.py`, parametrized over the four folders and the fixture rules; plus a collection-time guard in the hook that raises `pytest.UsageError` when an item lies outside the four folders.
- executed how: `uv run pytest --collect-only -q -m unit | tail -1` and the same for `-m integration`, `-m e2e`, `-m "integration and http"`, `-m db`, `-m redis`; counts in the PR, summing to the total.
- risk: `pytest.ini_options` markers must exist before `--strict-markers` sees them; `add_marker` with a name goes through pytest's marker generator, which enforces `--strict-markers`, so registration is required for the hook to work, not optional (checked by running).

### R3 — Docs, rules, skill, command map, ADR (S)  (human confirmation: `.claude/**` and `CLAUDE.md` are ask-first)
- files: `docs/decisions/ADR-0029-three-test-levels.md` (new; replaces the layout that task 3.3 put in the rules and the skill, as ADR-0011 left test layout to 3.3; ADR-0006's container and template decisions stand); `CLAUDE.md` (command map: `unit tests`, new `integration tests` = `uv run pytest tests/integration`, `e2e` = `uv run pytest tests/e2e`, plus the marker
  commands in one line); `.claude/rules/testing-python.md` (levels and layout, rule 4 naming, rule 20 markers now registered, the AAA shape); `.claude/rules/testing.md` (rule 9 points to the AAA convention);
  `.claude/skills/test-conventions/SKILL.md` (table, file paths, both examples relabelled and shown with AAA); `.claude/rules/project-structure.md` if it names the test folders; `.claude/rules/routes-convention.md` (the `paths:` glob);
  `docs/RUNBOOK.md` ("Database tests", "HTTP tests", "Redis" sections: paths, commands, marker table); `docs/ARCHITECTURE.md` (the `tests/` row); `docs/api/ERRORS.md` and
  ADR-0025/0026 only where they cite an old test path (stale path = bug, rule E2; the decision text is not touched).
- layer: docs.
- test: n/a; `grep -rn "tests/e2e" CLAUDE.md docs/*.md docs/api docs/decisions .claude/rules .claude/skills pyproject.toml` lists only paths that exist (old `docs/features/POC-*` plans and `.claude/.state` are history and stay untouched).
- executed how: run every command the new CLAUDE.md map and RUNBOOK show, from a clean checkout of the branch.
- risk: none beyond review.

### R4 — The AAA convention, written, not yet swept (S) (Q2 answered: labels `# Arrange` / `# Act` / `# Assert`, which are section markers, not explanatory comments under D6)
- files: part of R3 (`testing-python.md` rule 17 and the skill): one Act per test; three blocks separated by blank lines; labels `# Arrange` / `# Act` / `# Assert`; assertion subject last; when the Act sits inside
  `async with running_client(...)`, the label goes on the call, and the Assert follows after the block. A flow test with several requests is an Act of several calls only if they are one behaviour; otherwise it is split.
- executed how: both skill examples are run as a temporary file inside `tests/` (so `conftest.py` and `utils` resolve), then deleted.

## Follow-up PRs (outline only; own ticket, own approval)
- **POC-3.5 AAA sweep (L)**: one commit per folder (unit, integration/db, integration/http, e2e), about 646 tests; assertions are never changed (rule B3), only labels, blank lines, hoisting setup,
  and splitting tests with more than one Act. A diff-check script in the PR compares the AST of the asserts before and after.
- **POC-3.6 mock and data audit fixes (M)**: the table below.

## Mock and data audit (what the deck covers vs this repo)
| Deck topic | State here | Verdict |
|------------|------------|---------|
| Real DB, testcontainers, template + rollback (slides 19-21) | done (`db_session`, template DB per session, copy per module) | nothing to do |
| `time-machine` for the clock | `frozen_clock` | nothing to do |
| Fake over Mock (`FakeQueue`) | `utils/queue.py`, with its own unit test | nothing to do |
| `Mock(spec=)` / `create_autospec` | used (`test_queue.py`, `test_db_session.py`) | keep; no bare `MagicMock` exists |
| `respx` for outbound HTTP | the app has no HTTP client (SMS/email are log-only, P3) | not needed now; add with the first provider |
| `pytest-mock` (`mocker`) | absent; `monkeypatch` + autospec cover 100% of uses | do not add |
| Mock of own code in a DB test | `integration/db/test_db_session.py` patches `create_engine` and `run_seeds` and needs no database | move to `unit` (POC-3.6) |
| Spy wrappers on `hash_secret`/`verify_secret` (8 hand-written copies in 6 files) | assert "one Argon2 check per call", a stated non-negotiable | keep the tests, one shared `CallCounter` helper in `tests/utils/` |
| Factories (slide 18) | none; `make_app` copied in 15 files, `unique_email` in 7, row builders inline | `tests/utils/factories.py` + fixtures `make_app`, `make_account`; replace copies |
| `polyfactory` for Pydantic payloads | not present | not needed: payloads are 2-3 fields; revisit if schemas grow |
| `-ra` in `addopts` | absent | added in R2 (non-passed summary; it hides nothing and weakens nothing) |
| pytest 9 `subtests`, loop scope `session` | not used; per-function loop scope kept | no change |
| `tmp_path`, `caplog`, `capsys` | `isolated_settings_env` autouse covers env and cwd | nothing to do |

## Docs to update in this PR
- [ ] docs/features/POC-3.4/spec.md (acceptance criteria AC1-AC5 checked off)
- [ ] docs/ARCHITECTURE.md — the `tests/` row
- [ ] docs/DOMAIN_GLOSSARY.md — none (no domain term)
- [ ] docs/decisions/ADR-0029 — three test levels and path-based markers
- [ ] docs/RUNBOOK.md, CLAUDE.md, `.claude/rules/testing*.md`, the `test-conventions` skill

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| A test locates a file with `Path(__file__).parents[n]`, which shifts by one level | red test after the move | `grep -rn "parents\[\|__file__" tests` before R1; run the moved folder first |
| Basename collision or stale `__pycache__` after `git mv` | collection error | `find tests -name 'test_*.py' -printf '%f\n' \| sort \| uniq -d` is empty; clear caches |
| Path-based hook misclassifies a test that needs Postgres but sits in `integration/http` | `-m "not db"` runs a DB test without Docker and fails | R2 guard: `db` is also added from fixture names; check `-m "not db"` runs with Docker stopped |
| Muscle memory / IDE configs still call `pytest tests/e2e` | looks like 224 tests vanished | PR body and RUNBOOK say it plainly; AC2 shows the totals |
| The AAA labels read as comments breaking rule D6 | review friction | Q2 is answered (labels); the rule text says they are section markers |

## Assumptions
- A1 Three levels as in slide 22: integration = real Postgres or app in process; e2e = real process. A2 Ticket IDs POC-3.4 to 3.6 (Q1). A3 Test file names stay as they are. A4 `test_health.py` and `test_body_limit.py` are HTTP integration tests that need no database.
- A5 `test_worker_arq.py`, `test_shutdown.py` and `test_db_seed_entrypoints.py` are the only e2e tests today (each starts a process). A6 No new dependency, no CI change. A7 Marking by path through a hook (Q3).
