# ADR-0014 — Opt-in column mixins and Prisma-shaped constraint names

- **Date:** 2026-10-30
- **Status:** accepted; the task 2.5 parity-diff wording is superseded by [ADR-0019](ADR-0019-schema-parity-not-diffed.md)
- **Deciders:** volodymyr
- **Ticket:** POC-2.1
- **Supersedes:** one bullet of [ADR-0004](ADR-0004-data-layer-sqlalchemy-alembic.md): "a shared mixin carries only the `deleted` flag. Ids and timestamps follow each Prisma model and are declared per table". The rest of ADR-0004 stands.

## Context
Scope-doc row 2.1 asks for mixins for `id`, `createdAt`, `updatedAt` and `deleted`. ADR-0004 allowed only one, because the Prisma models do not all carry all four columns. Read from the Node base (`api/prisma/models/*.prisma`):

| Column | Prisma | Database type | Which tables |
|--------|--------|---------------|--------------|
| `id` | `String @id @default(uuid(4))`, no `@db.Uuid` | `TEXT NOT NULL`, no database default (the client generates the uuid) | `Account`, `AccountRole`, `AccountIdentity`, `AccountProfile`, `File`, `Notification`, `DeletedHistory`; not `AccountOnRole` or `NotificationRecipient` (composite keys) |
| `createdAt` | `DateTime @default(now())` | `TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP` | `Account`, `File`, `Notification` |
| `updatedAt` | `DateTime? @updatedAt` | `TIMESTAMP(3)`, nullable | `Account`, `File`, `Notification` |
| `deleted` | `Boolean @default(false)` | `BOOLEAN NOT NULL DEFAULT false` | every domain table except `DeletedHistory` |

Prisma's `@updatedAt` is filled by the client on create and on every update, so a Node row has `updatedAt` set from its first insert even though the column is nullable. The scope row says "uuid4 id", but the database column is `text`; the value is a uuid4 string.

## Decision
- `app/core/db.py` holds three independent, opt-in mixins. A table takes only the ones its Prisma model has; a mixin never decides that a table has a column (2.2 and 2.3 choose per model, 2.5 flags any difference).
  - `IdMixin`: `id` as `TEXT` primary key, default `str(uuid.uuid4())` generated in Python, no database default.
  - `TimestampMixin`: `createdAt` as `TIMESTAMP(3)` without time zone, not null, database default `CURRENT_TIMESTAMP`; `updatedAt` as `TIMESTAMP(3)` without time zone, nullable in the database, filled by the application on insert and on every update.
  - `SoftDeleteMixin`: `deleted` as `BOOLEAN`, not null, default false in Python and in the database (rule P6).
- Timestamps are UTC, stored as naive datetimes: the columns have no time zone, and asyncpg refuses an aware datetime for such a column. The engine sets the session time zone to UTC on every connection, because `CURRENT_TIMESTAMP` fills a column without a time zone in the session's own zone (a database server on `Europe/Kiev` stored `createdAt` two hours ahead of the UTC `updatedAt` until this was set).
- A table that differs (`AccountOnRole`'s composite key) declares those columns itself. (The Node `Migration` table, whose `createdAt` was nullable, is not mapped: ADR-0018.)
- `Base.metadata` carries a naming convention that reproduces Prisma's names: `<Table>_pkey`, `<Table>_<cols>_key` for uniques, `<Table>_<cols>_idx` for indexes and `<Table>_<col>_fkey` for foreign keys. This is a target; task 2.5 proves it by diffing `pg_dump --schema-only`.

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| Only `SoftDeleteMixin` (ADR-0004 as written) | repeats the id and timestamp columns in six tables, each a chance to drift from Prisma |
| One mixin with all four columns | forces a nullable `createdAt` or a missing key onto tables that do not have it |
| A `uuid` column type for `id` | not what Prisma emitted; would show up as a diff in 2.5 |
| A database default for `updatedAt` | Prisma has none; the application fills it |

## Consequences
- Positive: the Prisma column shapes are written once and tested against a real Postgres.
- Accepted cost: a mixin that disagrees with a table's Prisma model is only caught by reading the model (2.2, 2.3) or by the parity diff (2.5).
- Follow-ups: tasks 2.2 and 2.3 use the mixins; 2.5 confirms the types and names against `pg_dump`.

## Revisit when
The parity diff in 2.5 shows a column shape the mixins do not reproduce, or schema parity with the Node base stops mattering.
