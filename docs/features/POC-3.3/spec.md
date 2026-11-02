# POC-3.3 — Test conventions for pytest

## Problem
The test base exists (3.1 database fixtures, 3.2 client, auth helper, fake queue, frozen clock) but no document tells the next
developer or agent how to use it. `.claude/rules/testing-python.md` is a generic Python rule file written for hardware and GUI
projects: it says `tests/test_<module>.py`, talks about serial devices and import-time singletons, and never mentions
`tests/unit`, `tests/e2e`, `db_session`, `client`, `queue` or `frozen_clock`. The skill `.claude/skills/test-conventions/SKILL.md`
named by the scope doc does not exist in this repo. `project-structure.md` and `ARCHITECTURE.md` still say the layout is "set by task 3.3".

## Goal / business value
Goal 3 (Test base, BUSINESS_MODEL.md): "easy to extend". Packages 4 to 9 add about 25 test files; they should all follow one style (rule D1).

## Scope
- in: rewrite `.claude/rules/testing-python.md` for this repo (layout, fixtures, boundary mocks, determinism, markers); create
  `.claude/skills/test-conventions/SKILL.md` with a copy-paste unit example and a copy-paste e2e example that run; replace the
  "set by task 3.3" wording in `project-structure.md` and `ARCHITECTURE.md`; RUNBOOK pointer.
- **out (explicit):** `testing.md` (language-neutral, plugin-managed), new fixtures or helpers, moving or renaming existing tests,
  CI, new markers or plugins, any `app/` change, `pyproject.toml` change.

## Acceptance criteria
- [x] AC1 `testing-python.md` states: `tests/unit` (no Docker, no database, no network) vs `tests/e2e` (real Postgres and/or the app over HTTP, rule P8), flat `test_<area>.py` files, the fixtures of `tests/conftest.py` and when to use each, and the boundary list (clock, queue, network, SMS/email; never the database or the unit under test).
- [x] AC2 Hardware, GUI, serial and import-time-singleton rules are gone; no rule contradicts `testing.md` or CLAUDE.md (B3: no skip/xfail without `WHY:`).
- [x] AC3 `.claude/skills/test-conventions/SKILL.md` exists with valid frontmatter, a decision table (which level, which fixture) and one unit and one e2e example.
- [x] AC4 Both examples, copied verbatim into `tests/unit/` and `tests/e2e/`, pass under `uv run pytest`, `ruff check`, `ruff format --check` and `mypy` (copies removed afterwards).
- [x] AC5 No remaining "set by task 3.3" text in `project-structure.md`, `ARCHITECTURE.md`; every fixture and path the rules name exists (checked with grep).
- [x] AC6 `ruff check`, `ruff format --check`, `mypy`, `pytest tests/unit` and `pytest tests/e2e` pass; no existing test touched.

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| Test needs the database but not HTTP (model tests) | e2e, using `db_session` | existing `tests/e2e/test_db_*_models.py` |
| Test needs the app but no database | e2e, `running_client(create_app(Settings()))` | RUNBOOK "HTTP tests" |
| Rule text names a fixture that later changes | rules name fixtures and point to `tests/conftest.py` docstrings, not copy them | keeps one source of truth |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| Q1 | Rewrite `testing.md` too (scope doc says `testing*.md`)? | no: it is neutral and plugin-managed; only `testing-python.md` is repo-specific. | no |
| Q2 | Mirror `app/` under `tests/unit/` (`tests/unit/services/...`)? | no: keep today's flat layout, name by area (`test_<area>.py`); revisit when a directory passes about 20 files. | yes, if you want a mirror |
| Q3 | Plugin `/setup` may overwrite `.claude/rules/*` on update. | accept; the PR body notes it and the file keeps the repo-specific header. | no |
