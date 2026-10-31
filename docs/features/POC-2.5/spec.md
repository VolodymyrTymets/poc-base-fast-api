# POC-2.5 — Migration smoke run, parity diff dropped

Scope-doc row 2.5 (3 h): "Schema parity: migrate DB A with `prisma migrate deploy`, DB B with Alembic, diff `pg_dump --schema-only`" (`scripts/schema_parity.sh`;
acceptance: diff empty or each line explained). Depends on 2.4 (merged, PR #10). **The human changed the task** (2026-10-31): no diff, no Prisma, no script. Reason given:
the two schemas need not be identical and the human already checked the new schema by hand. What remains is to run the Alembic migration on a fresh PostGIS database and start the app.

## Problem
ADR-0004, 0014, 0015, 0017, 0018, `docs/ARCHITECTURE.md` and comments in `app/` say task 2.5 "proves" parity with a `pg_dump` diff. That will never run, so those
lines would be stale (rule E2), and the decision "parity is a target proven by a diff" needs a superseding ADR (rule P2). Nobody has yet run `alembic upgrade head` and the app together on a clean database.

## Goal / business value
Goal 1 (scaffolding): a fork can trust that one command builds the schema and the app boots on it; the docs say what is actually promised.

## Scope
- in: a throwaway PostGIS container, `alembic upgrade head`, `alembic check`, start the app with `DATABASE_URL`, `GET /api/v1/health`; new ADR-0019; pointers and wording fixes in the documents and comments that mention 2.5.
- **out (explicit):** any `pg_dump` diff, Prisma, the Node repo, `scripts/`, a new test or script, CI/Docker/compose files, a change to the models or the revision's SQL, the scope doc (human's), a new revision.

## Acceptance criteria
- [ ] AC1 Given an empty PostGIS database in Docker, when `uv run alembic upgrade head` runs, then it exits 0 and `alembic_version` holds `0001_init`.
- [ ] AC2 Given that database, when `uv run alembic check` runs, then it reports no new upgrade operations.
- [ ] AC3 Given `DATABASE_URL` pointing at it, when `uv run poc-base-fast-api` starts, then `GET /api/v1/health` answers `{"status":"ok"}` and SIGTERM stops it cleanly. (The route opens no database connection, so this shows the app boots with the URL set; reading the schema is Not verified.)
- [ ] AC4 ADR-0019 exists (status accepted) and says parity is a naming target, not proven by a diff, and that the schema may differ from the Node base's.
- [ ] AC5 Outside the accepted ADR bodies, no document or comment says task 2.5 diffs `pg_dump` or "proves" parity; each of ADR-0004/0014/0015/0017/0018 carries an `Amended by ADR-0019` line (their bodies stay as history). The merged `0001_init.py` comments stay untouched; ADR-0019 covers them.
- [ ] AC6 `ruff check`, `ruff format --check`, `mypy`, `pytest tests/unit` pass; the container is removed afterwards.

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| Port 5432 or 3003 is taken (another project's Postgres runs on 3003) | use a fresh container of my own on a free port; never touch the other project's containers | rule C4 |
| `.env` holds a `DATABASE_URL` | export the container URL in the shell; it wins over `.env` (RUNBOOK) | RUNBOOK |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| Q1 | Leave the merged `migrations/versions/0001_init.py` alone, including its comment that cites 2.5? | Yes, untouched (rule "an applied revision is never edited"); ADR-0019 says the comment is superseded | no |
| Q2 | Create and remove my own container `poc-base-fast-api-smoke` (`postgis/postgis:16-3.4`, already pulled locally)? | Yes; I ask for confirmation in chat right before the `docker run` and again before `docker rm -f`, for that exact name only | yes (C4) |
| Q3 | Older ADRs keep their text and get one "Amended by ADR-0019" line, not a rewrite? | Yes (accepted ADRs are history) | no |
