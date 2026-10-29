# POC-1.3 — Project structure: root `app/` laid out by layer

## Problem
The repo has one stub package, `src/poc_base_fast_api/`. The scope-doc row for 1.3 (read again on 2026-10-29, rev 114) fixes the
structure: a root `app/` laid out by layer, where every Nest module becomes `routers/<module>.py`, `schemas/<module>.py`,
`models/<module>.py` and `services/<module>.py` for the modules `account`, `account_profile`, `account_role`, `auth`, `files`
and `notifier`; cross-cutting code (DB session, errors, logging, validation, JWT, cache, pagination) goes in `core/`; shared
`Depends` in `dependencies.py`; settings in `config.py`; background jobs in `workers/`; seed items in `seeds/`; plus a
`project-structure.md` rule to fix the structure. The other rows of the scope doc already cite these paths
(`app/core/db.py`, `app/models/file.py`, `app/services/otp.py`, ...). ADR-0010 chose `src/poc_base_fast_api/` instead.

## Goal / business value
Goal 1 (project scaffolding): a fork finds each kind of code in one obvious place, and a rule stops an agent from putting
code anywhere else.

## Scope
- in: ADR-0011 (root `app/` package, layered; supersedes the package-location part of ADR-0010); the move (`pyproject.toml`
  build settings and script entry); the skeleton below; `.claude/rules/project-structure.md`; `docs/ARCHITECTURE.md`.
- the skeleton (each new module holds only a docstring saying what it will hold and which tasks fill it):
  - `app/main.py`, `app/config.py`, `app/dependencies.py`;
  - for each layer `routers`, `schemas`, `models`, `services`: an `__init__.py` and one file per module, six modules, so 4 x 7 = 28 files;
  - `app/core/__init__.py`, `app/workers/__init__.py`, `app/seeds/__init__.py`;
  - `tests/.gitkeep`.
- **out (explicit):** any dependency (C2; FastAPI is 1.5, tooling 1.4); real content in any module (packages 1.5 to 9);
  the individual `core/` files (`db.py`, `errors.py`, ...), which the tasks that need them add; `.env` and `.env.example`
  (1.5); a test runner and the first test (1.4); `web/`, `api/`, compose, ports, Docker (ADR-0010, 11.1, 11.2); editing the
  scope doc (the human does; lines to change are listed in the PR).

## Acceptance criteria
- [x] AC1 Given a fresh clone, when I run `uv sync`, then it succeeds with no dependency added, and `uv run python -I -c "import app"` works.
- [x] AC2 The tree equals the list above (35 `.py` files under `app/`, `tests/.gitkeep`); `src/` is gone.
- [x] AC3 Every module except `app/__init__.py` holds only a docstring (34 files).
- [x] AC4 `uv build` produces a wheel whose only top-level module is `app` and which contains all 35 `.py` files and nothing from `tests/`; `uv run poc-base-fast-api` still prints its greeting.
- [x] AC5 `.claude/rules/project-structure.md` exists with `paths:` matching `app/**` and `tests/**`, states the layers, `core/`, `workers/`, `seeds/`, the import direction and where a new feature's files go, and says a new top-level module or layer needs an ADR.
- [x] AC6 ADR-0011 is accepted and passes the ADR checks used in POC-1.1; ADR-0010 carries a note that its package location is superseded; `docs/ARCHITECTURE.md` shows the new layout and has no `src/poc_base_fast_api` left.
- [x] AC7 The diff touches only `app/`, `tests/`, `pyproject.toml`, `.claude/rules/`, `docs/`, and removes `src/`.

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| A module has no file in some layer in later tasks (for example no router for `notifier`) | the file still exists from this task, docstring-only, as the row says "every module"; a later PR may delete an unused one | scope doc, open question 1 |
| The first half of the 1.3 row (copy `web/`, compose, `set-ports.sh`, `move-env.sh`; work in `api/`) | superseded by ADR-0010: no `web/`, compose and ports are task 11.2, `api/` is the repo root | ADR-0010 |
| `app` is a generic top-level name that would collide beside another project's `app` | accepted: an application deployed alone | this plan |
| `[project.scripts]` points at `poc_base_fast_api:main` | becomes `app:main`; the greeting stub moves to `app/__init__.py` until 1.5 | this plan |
| `tests/` is empty until 1.4 | kept in git with a `.gitkeep` | this plan |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| 1 | Create the full 6 x 4 grid, although later rows cite only some files (no router or schema for `notifier`, none of `account_role` outside `models` and `services`)? | Yes, as the row says "every Nest module"; unused files can be removed later | confirm |
| 2 | Does this reverse ADR-0010's `src/poc_base_fast_api/`? | Yes, through ADR-0011, as rule P2 requires | confirm |
| 3 | Is `tests/` created now? | A `.gitkeep` only; the first test and the runner come with 1.4 | no |
