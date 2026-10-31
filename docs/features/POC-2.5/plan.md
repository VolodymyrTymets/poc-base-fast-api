# POC-2.5 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     Approving confirms the assumed answers in spec.md. Q2 (one Docker container, rule C4) is confirmed again in chat just before `docker run` and before `docker rm -f`.
     Approved-by: <name> · <date> -->
Approved-by: volodymyr · 2026-10-31

Pattern followed: `docs/decisions/ADR-0018-drop-migration-table.md` (an ADR that amends an earlier parity decision, with the same header fields and sections) and the runbook's "Migrations" section for the commands.
No code precedent is needed: no code behaviour changes. Library facts (Alembic CLI) are already in RUNBOOK and verified in 2.4.

## Contract changes
- boundary: none (no endpoint, setting or CLI change).
- data: none. The smoke run uses a throwaway database that is removed.
- generated output: none.

## Requirements (ordered; R1 changes no file, so the commits are R2 and R3; branch `chore/POC-2.5-drop-parity-diff`, one draft PR)

### R1 — Smoke run on a fresh PostGIS database (S)
- files: none changed. Evidence is the command output, pasted into the PR.
- layer: none.
- test: none new (human decision: docs and ADR only). Existing `tests/e2e/test_db_migrations.py` is not rerun as the proof.
- executed how: `docker run -d --name poc-base-fast-api-smoke -e POSTGRES_PASSWORD=... -p 5440:5432 postgis/postgis:16-3.4`; wait for `pg_isready`;
  `docker exec ... psql -c 'create database smoke_empty'` and `export DATABASE_URL=postgresql+asyncpg://postgres:...@localhost:5440/smoke_empty` (changed during the run: `alembic check` fails on the image's default `postgres` database, see the spec's edge cases); `uv run alembic upgrade head`; `uv run alembic check`; `psql` (via `docker exec`) `select * from alembic_version` and `\dt` count;
  `uv run poc-base-fast-api &`, `curl localhost:3001/api/v1/health`, `kill -TERM` (the health route opens no database connection: it shows that the app boots with the URL set, not that it reads the schema; the database evidence is the `alembic` and `psql` output, and "app reads the migrated schema" goes under "Not verified"); then `docker rm -f poc-base-fast-api-smoke` (each of the run and the remove only after an explicit yes in the same message, C4). Throwaway password, never committed or logged (A6).
- risk: port 3001 busy or the image missing offline. Cheapest check: `lsof -i :3001`, `docker image ls postgis/postgis` before starting. If `check` reports a diff, stop and report (B4), do not edit the revision.

### R2 — ADR-0019 and pointers (S)
- files: `docs/decisions/ADR-0019-schema-parity-not-diffed.md` (new, ADR template: supersedes the "task 2.5 proves it" part of ADR-0004, ADR-0014, ADR-0015, ADR-0017, ADR-0018; keeps the naming target and the three known differences `SSN`, `is18YearOld`, `Migration`; says no diff is run and why: the human checked the schema by hand),
  `docs/decisions/ADR-0004`, `0014`, `0015`, `0017`, `0018` (change: append `; the task 2.5 diff/proof part is superseded by [ADR-0019](...)` to the Status line, the repo's convention e.g. ADR-0004:4; no body rewrite). ADR-0019 has a `- **Supersedes:**` header naming those parts.
- test: `grep -L "ADR-0019" docs/decisions/ADR-00{04,14,15,17,18}*` prints nothing; ADR-0019 exists with status accepted (AC4).
- executed how: that output, pasted.
- risk: none.

### R3 — Stale wording in architecture, code comments (S)
- files: `docs/ARCHITECTURE.md` (change: the "proven by task 2.5" and "parity diff of task 2.5" lines, an ADR-0019 bullet, and the ranges "ADR-0003 to ADR-0015" in the status line and "ADR-0003 to ADR-0018" in the heading, both to ADR-0019), `app/core/db.py`, `app/models/account_role.py`, `app/models/file.py`, `tests/unit/test_initial_revision.py`, `docs/features/POC-2.5/spec.md` (ACs checked off).
- layer: docs and comments only; no statement changes. `migrations/versions/0001_init.py` is not touched (Q1).
- test (AC5, after the edits): `grep -rnE "2\.5|pg_dump|proven" app tests` prints nothing; in `docs/` the same pattern with `--exclude-dir=features --exclude=ADR-0004* --exclude=ADR-0014* --exclude=ADR-0015* --exclude=ADR-0017* --exclude=ADR-0018*` prints only lines of ADR-0019 and `docs/ARCHITECTURE.md` that state the new position (listed in the PR). `migrations/versions/0001_init.py:132` still matches and is superseded. Also `git diff -U0 -- app tests | grep '^[+-]' | grep -vE '^(\+\+\+|---)' | grep -vE '^[+-]\s*#'` prints nothing (comment lines only); `git diff --stat` shows `migrations/` absent.
- executed how: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest tests/unit`, outputs pasted (AC6).
- risk: a comment edit changes a line number a test reads. The unit test run catches it.

## Docs to update in this PR
- [ ] docs/features/POC-2.5/spec.md (ACs checked)
- [ ] docs/decisions/ADR-0019 (new) and the five pointer lines
- [ ] docs/ARCHITECTURE.md (rule E1: decisions list)
- [ ] docs/RUNBOOK.md: no change needed (its migration commands were verified by R1); DOMAIN_GLOSSARY: no new term
- scope doc row 2.5 text and status are the human's (rule E2: noted in the PR body)

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| `alembic check` reports a diff on a clean PostGIS 16 (2.4 tested PG 18) | AC2 fails | first thing in R1; stop and report, no revision edit |
| A reworded comment breaks ruff line length or formatting | AC6 | R3 runs ruff, format check and mypy |
| The other project's containers on 3003/3004 get touched | rule C4 | use own container name and port 5440; `docker rm -f` only that name |

## Assumptions
- Spec Q1 to Q3 hold; the stale comment in the merged revision is left and superseded by ADR-0019. Date 2026-10-31. Python is the `uv` interpreter (3.14, T2).
- Estimate: R1 S, R2 S, R3 S, well under the scope doc's 3 h.
