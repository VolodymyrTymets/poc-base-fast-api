# POC-2.2 — Account models

Scope-doc row 2.2 (4 h). Depends on 2.1 (merged, PR #7). The ticket text: "Account models: `AccountRoleType`, `Account`, `AccountRole`,
`AccountOnRole`, `AccountIdentity`, `AccountProfile`; PascalCase relationships (P1); all indexes and uniques of `account.prisma`".
Acceptance in the doc: "mypy passes; metadata lists every table and index of `account.prisma`". Reference:
`../poc-base/api/prisma/models/account.prisma` and the DDL in `../poc-base/api/prisma/migrations/` (init plus `kan_12_password_auth`).

## Problem
No table is mapped. Alembic (2.4), the test base (3.1) and every account service (packages 5 to 8) need the account tables as
SQLAlchemy models whose names, types, keys and indexes are the Prisma ones, so a fork reads the same data model as the Node base.

## Goal / business value
Goal 2 (authentication): the identity, profile and role tables are what the OTP and password flows store into. Goal 1: a fork gets
the account data model without redrawing it. Non-negotiables: soft delete only (`deleted` on every table here), refresh token stored
as a hash (the `refreshToken` column holds `sha256`, ADR-0008, never bcrypt).

## Scope
- in: enum `AccountRoleType`; models `Account`, `AccountRole`, `AccountOnRole`, `AccountIdentity`, `AccountProfile` in the three
  files named by the scope row (`AccountIdentity` in `account.py`, `AccountOnRole` and the enum in `account_role.py`, per the
  stubs); columns, primary keys, foreign keys with Prisma's `ON DELETE`/`ON UPDATE`, every index and unique; relationships between
  these five tables; `app/models/__init__.py` imports the modules so `Base.metadata` lists the tables; unit and real-Postgres tests; docs.
- **out (explicit):** the `File` and `Notification*` tables and every relationship or foreign key that points at them (2.3, see Q1);
  Alembic and `CREATE TYPE` migrations (2.4); the `schema.prisma` parity diff (2.5); services, schemas and routers for accounts
  (packages 5 to 8); seeds of the two roles (5.1); password, OTP and token logic; any new dependency.

## Acceptance criteria
- [x] AC1 Given `import app.models`, then `Base.metadata.tables` holds exactly `Account`, `AccountRole`, `AccountOnRole`,
  `AccountIdentity`, `AccountProfile`, each with the Prisma column names (quoted, mixed case), types, nullability and defaults of the init and `kan_12` migrations.
- [x] AC2 Given the metadata, then every index and unique of `account.prisma` exists with Prisma's name: `Account_createdAt_idx` (`createdAt DESC`),
  `AccountRole_type_key` (unique) and `AccountRole_type_deleted_idx`, `AccountOnRole_deleted_idx`, `AccountIdentity_accountId_key` (unique),
  `AccountIdentity_resetTokenHash_key` (unique), `AccountIdentity_deleted_idx`, `AccountProfile_accountId_key` (unique),
  `AccountProfile_email_key` (unique), `AccountProfile_deleted_idx`; primary keys `<Table>_pkey` (`AccountOnRole` composite `roleId, accountId`).
- [x] AC3 Given the foreign keys, then they carry Prisma's actions: `Account.lastAccountRoleId` `ON DELETE SET NULL`; `AccountOnRole.roleId`/`accountId`,
  `AccountIdentity.accountId`, `AccountProfile.accountId` `ON DELETE RESTRICT`; all `ON UPDATE CASCADE`.
- [x] AC4 Given a real Postgres, when the tables are created from the metadata, then `pg_indexes` and `pg_constraint` show the same indexes (including `DESC` and `UNIQUE`) and foreign-key actions as AC2 and AC3.
- [x] AC5 Given the relationships, then `configure_mappers()` succeeds and the names are `Account.AccountIdentity`, `AccountProfile`, `AccountOnRole`, `LastAccountRole`;
  `AccountRole.AccountOnRole`, `accounts`; `AccountOnRole.AccountRole`, `Account`; `AccountIdentity.Account`; `AccountProfile.Account` (Prisma's names, P1), each pair linked both ways.
- [x] AC6 Given a graph of one account with identity, profile, a role and a role link, when it is inserted and read back on a real Postgres, then the relationships load and `updatedAt` is set; a second `AccountRole` of the same `type`, a second identity or profile for one account, a repeated `email` or `resetTokenHash`, and an `AccountOnRole` row naming a missing role or account are each refused by the database.
- [x] AC7 `uv run mypy` passes (strict) on the new modules and tests.
- [x] AC8 Docs match: ARCHITECTURE, DOMAIN_GLOSSARY (identifiers now decided; the PascalCase line confirmed).

## Built differently from the plan
- `relationship(foreign_keys=...)` is not used: `Account` and `AccountRole` are linked by one foreign key directly (`lastAccountRoleId`) and `AccountOnRole` has one foreign key to each, so SQLAlchemy finds no ambiguous join (`configure_mappers()` passes).
- Each relationship also names its target as a string. Without it, an annotation such as `Mapped[AccountRole]` inside the `AccountRole` class resolved to the class attribute of that name and recursed forever in `configure_mappers()` (mypy did not see it).
- The real-Postgres test file is `tests/e2e/test_db_account_models.py`: the same basename as the unit test collided in mypy (no `__init__.py`), and the other database tests use the `test_db_*` pattern. The enum type followed `schema_translate_map`, so Q5's primary path held and no fallback was used.

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| `lastLoginAt` has no default in Prisma (`NOT NULL`) | required column, the service supplies it; no default invented | Prisma DDL |
| `Account.updatedAt` nullable but set by the app | `TimestampMixin` already does this | ADR-0014 |
| Prisma's unique is `CREATE UNIQUE INDEX`, not a `UNIQUE` constraint | declare `Index(..., unique=True)` with the `_key` name so `pg_dump` matches in 2.5 | Prisma DDL |
| Two foreign-key paths between `Account` and `AccountRole` (`lastAccountRoleId` and `AccountOnRole`) | the join is unambiguous (each pair of tables has one direct foreign key), so no `foreign_keys=` is needed; `configure_mappers()` is the check | SQLAlchemy |
| `dataOfBirth` (sic) holds a date as text | column keeps the name for parity; Python attribute is `date_of_birth`; no type change | Q3 |
| Column holding secrets (`hash`, `salt`, `otpHash`, `refreshToken`, `resetTokenHash`, `SSN`) | no `__repr__` or log line lists model columns (rule D8, P4) | CLAUDE.md |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| Q1 | `AccountProfile.avatarId` is a foreign key to `File`, and `Account.Files`, `Account.NotificationRecipient`, `AccountProfile.Avatar` point at tables 2.3 builds. A `ForeignKey("File.id")` or a relationship to a class that does not exist makes `create_all` and `configure_mappers` fail. | 2.2 declares `avatarId` as a plain nullable `text` column. 2.3 adds the `AccountProfile_avatarId_fkey`, `AccountProfile.Avatar`, `Account.Files` and `Account.NotificationRecipient` when it creates `File` and `Notification*`, so 2.3 also edits `account.py` and `account_profile.py` (its row lists neither). AC1 to AC3 then cover everything except that one foreign key. | **yes**, it changes the 2.3 file list |
| Q2 | Python names | snake_case attributes mapped to the exact quoted column names (the 2.1 pattern: `created_at` to `"createdAt"`, `ssn` to `"SSN"`, `is_18_year_old` to `"is18YearOld"`); class names and relationship names are Prisma's, so P1 is confirmed for SQLAlchemy, including the lower-case `accounts` that Prisma itself uses. | confirm |
| Q3 | Fix the `dataOfBirth` typo? | No: the column name is a parity target (ADR-0004). The Python attribute is `date_of_birth`, a comment says why the column differs. | confirm |
| Q4 | Python type of the enum | `enum.StrEnum` mapped with `sqlalchemy.Enum(..., name="AccountRoleType")`; the PostgreSQL type is created by `create_all` here and by Alembic in 2.4. | confirm |
| Q5 | Does the real-Postgres test create tables in the scratch database (as 2.1 does) or in a throwaway schema? | A throwaway schema through `schema_translate_map`, so a developer's own `"Account"` table is never dropped. The enum experiment runs first in R3. If the enum does not follow the translate map, the fixture fails when `"Account"` already exists rather than dropping anything, and any other path stops and asks the human (rule C4). The test database is a scratch one named in `.env.test`, never the default `postgres` database. | confirm |
| Q6 | `tests/unit/test_db_base.py:58` asserts `Base.metadata` has no tables. It stops being true by design. | Replace it with an exact set equality between the tables on `Base.metadata` and the five `app.models` tables (it still fails if a scratch test model lands on the real `Base`) in the R1 commit; the reason is in the PR and in a `WHY:` comment. This edits an existing assertion (rule B3). | **yes**, B3 needs the human's approval |
