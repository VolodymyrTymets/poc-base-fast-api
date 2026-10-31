# ADR-0019 — Schema parity with the Node base is a naming target, not proven by a diff

- **Date:** 2026-10-31
- **Status:** accepted
- **Deciders:** volodymyr
- **Ticket:** POC-2.5
- **Supersedes:** the sentences of ADR-0004, ADR-0014, ADR-0015, ADR-0017 and ADR-0018 that say task 2.5 proves parity by diffing `pg_dump --schema-only` of a Prisma-migrated and an Alembic-migrated database (and, in ADR-0015 and ADR-0018, that the diff expects exactly three differences). Everything else in those ADRs stands.

## Context
The scope doc's row 2.5 planned a `scripts/schema_parity.sh` that migrates database A with `prisma migrate deploy`, database B with Alembic, and diffs the two dumps. The human checked the new schema by hand
and decided the two schemas do not have to be identical. The diff would need the Node repo, Node and Prisma on every machine that runs it, for a result nobody depends on.

## Decision
- Table, column, index and constraint names still follow the Prisma schema where the models and `0001_init` were written from it (ADR-0004, ADR-0014). That is a convention for new code, not a promise checked by a tool.
- No `pg_dump` diff, Prisma step or `scripts/schema_parity.sh` exists in this repo, and none is planned.
- The known differences from the Node schema stay as decided: no `AccountProfile.SSN` or `is18YearOld` (ADR-0015) and no `Migration` table (ADR-0018). Other differences are allowed; a change that needs one is made in a new revision with a note in its ADR or PR.
- Task 2.5 is a smoke run: `alembic upgrade head` and `alembic check` on a fresh PostGIS database, then the app started with `DATABASE_URL`.
- The comment at `migrations/versions/0001_init.py` that mentions the task 2.5 diff is left as it is, because an applied revision is not edited; this ADR overrides it.

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| Build the diff script as planned | needs the Node repo and Prisma to run; the human does not need identical schemas |
| Diff against a saved Prisma dump | a frozen dump goes stale and still needs someone to explain every line |

## Consequences
- Positive: no cross-repo tooling; the docs promise only what is checked (`alembic check` against the models).
- Accepted cost: nothing automatic catches a drift from the Node names; a fork that moves data between the two bases checks that by hand.
- Follow-ups: task 3.1 builds the test database from `0001_init`.

## Revisit when
A project must run the Node and Python bases against the same database, which needs a proven identical schema.
