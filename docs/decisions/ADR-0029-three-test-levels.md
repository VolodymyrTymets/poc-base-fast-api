# ADR-0029 — Three test levels, markers set by folder

- **Date:** 2026-11-04
- **Status:** accepted
- **Deciders:** volodymyr
- **Ticket:** POC-3.4
- **Supersedes:** the two-level test layout (`tests/unit`, `tests/e2e`) that task 3.3 wrote into `.claude/rules/testing-python.md` and the `test-conventions` skill (ADR-0011 left test layout to task 3.3). ADR-0006's container, template-database and fixture decisions stand.

## Context
`tests/e2e/` held 45 files, and 42 of them were integration tests in the sense of the course material (07-pytest, slides 3 and 22): an API or a service on a real Postgres, in one process.
Only three started a process of their own. Database-level and HTTP-level tests shared one folder, and no marker existed, so a fast tier could not be selected.

## Decision
- Three levels. **unit**: needs nothing outside the process (`tests/unit`). **integration**: a real Postgres or the app served in process through ASGI (`tests/integration/db` for services,
  models, seeds and migrations; `tests/integration/http` for endpoints and middleware). **e2e**: the test starts the app, the worker or a project command as its own process (`tests/e2e`).
- Markers `unit`, `integration`, `e2e`, `db`, `http`, `redis` are registered in `pyproject.toml` and set by one collection hook in `tests/conftest.py`: the level and area from the folder,
  `db` and `redis` also from the fixtures a test requests (`tests/utils/markers.py`). No file carries a `pytestmark`. A test outside the four folders stops the run.
- File names do not change and stay unique across all folders (there is still no `__init__.py`, so no import-mode change). The `db_` and `http_` prefixes are now redundant with the folder and are kept until a separate rename.
- Arrange-Act-Assert is the shape of every test body, labelled `# Arrange`, `# Act`, `# Assert`. The labels are section markers, not explanations, so rule D6 does not apply to them.
- Selection: `-m unit` on save, `-m "not e2e"` before a push, `-m "not db and not redis"` with no Docker.

## Consequences
- `uv run pytest tests/e2e` now runs 12 tests; the 438 integration tests are `uv run pytest tests/integration`.
- A fork that adds a process-level test puts it in `tests/e2e`; one that adds a service test, in `tests/integration/db`.
- Applying the labels to the existing tests is task POC-3.5, not this one.
