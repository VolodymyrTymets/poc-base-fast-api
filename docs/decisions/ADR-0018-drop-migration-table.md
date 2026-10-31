# ADR-0018 — Drop the Node `Migration` table

- **Date:** 2026-10-31
- **Status:** accepted; the task 2.5 diff wording is superseded by [ADR-0019](ADR-0019-schema-parity-not-diffed.md)
- **Deciders:** volodymyr
- **Ticket:** POC-2.4
- **Amends:** the schema-parity target of [ADR-0004](ADR-0004-data-layer-sqlalchemy-alembic.md) by one table, next to the two columns of [ADR-0015](ADR-0015-drop-ssn-and-is18yearold.md). Both otherwise stand.

## Context
The Node base has a `Migration` table (`name`, `successful`, `result`, `description`, timestamps) for recording runs of its own data migrations. This base keeps every schema change in Alembic, which records the applied revisions in its own `alembic_version` table (ADR-0004, ADR-0017). A second table for the same purpose would hold nothing Alembic does not already know, and nothing in this project writes to it. The human's reason: "while all migrations are controlled by Alembic we do not need the `Migration` model".

## Decision
- There is no `Migration` model in `app/models/` and no `Migration` table in revision `0001_init`. `DeletedHistory`, the other bookkeeping table of `system.prisma`, stays.
- Every other table keeps its Prisma name and shape; the base now has nine tables.
- Task 2.5's `pg_dump --schema-only` diff expects exactly three differences from the Node schema: the `AccountProfile.SSN` and `AccountProfile.is18YearOld` columns (ADR-0015) and the `Migration` table. Any further difference is still a finding.

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| Keep the table for exact parity | it would duplicate `alembic_version` and invite two sources of truth about what ran |
| Keep the model but out of the first revision | `alembic check` would report it as a missing table, and an unmapped table in the models is worse than none |
| Add a `0002` revision that drops it | revision `0001_init` was not merged when this was decided, so no database other than the author's had it; a drop revision would leave a table created and removed for no reader |

## Consequences
- Positive: one place records applied migrations; a smaller schema and glossary.
- Accepted cost: the schema is not byte-identical to the Node base's, so 2.5 must explain this table. A database that ran the earlier version of `0001_init` still has the table: downgrade it with the old revision first (`alembic downgrade base`), or drop the table by hand.
- Follow-ups: none; a fork that needs application-level migration bookkeeping adds a table with its own revision.

## Revisit when
A data migration needs a record that `alembic_version` cannot hold (per-run results, for one).
