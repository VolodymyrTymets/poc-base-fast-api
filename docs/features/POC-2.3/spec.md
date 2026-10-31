# POC-2.3 — File, notification and system models

Scope-doc row 2.3 (3 h). Depends on 2.2 (merged, PR #8). The ticket text: "`FileType`, `File` (`content` as `LargeBinary`), `Notification`,
`NotificationRecipient`, `DeletedHistory`, `Migration`. Also in `account.py` and `account_profile.py`: the `AccountProfile_avatarId_fkey` foreign key
with `AccountProfile.avatar`, `Account.files` and `Account.notification_recipients`; add the new tables to the set asserted in
`tests/unit/test_db_base.py`. Relationship names are snake_case (ADR-0016)." Files: `app/models/file.py`, `notification.py`, `system.py`.
Acceptance in the doc: "Same check for `files`, `notifications`, `system.prisma`. The avatar foreign key exists and `AccountProfile.avatar` loads the file".
Reference: `../poc-base/api/prisma/models/{files,notifications,system}.prisma` and the DDL of the four migrations in `../poc-base/api/prisma/migrations/`
(init, `kan_6_postgres_file_storage`, `kan_6_drop_file_status`, `kan_12_password_auth`). The final DDL is the sum of the four: `File.key` and
`File.status` are gone, `File.content` is added last, and the `FileStatus` enum no longer exists.

## Problem
Files, notifications and the two bookkeeping tables are not mapped, and `AccountProfile.avatarId` is a plain column with no foreign key. Task 2.4
(Alembic), 2.5 (parity diff) and the files and notifier packages (8, 9) need these as models with the Prisma names, types, keys and indexes.

## Goal / business value
Goal 1 (scaffolding): a fork gets the whole data model of the Node base. Goal 2 (auth) touches it through the avatar. Non-negotiable: soft delete only
(`deleted` on `File`, `Notification`, `NotificationRecipient`). Bytes stay in Postgres (`File.content`, ADR-0009).

## Scope
- in: enum `FileType`; models `File`, `Notification`, `NotificationRecipient`, `DeletedHistory`, `Migration`; columns, keys, foreign keys with Prisma's
  actions, the `File` and `DeletedHistory` indexes; the avatar foreign key and the relationships named above plus their other sides; `app/models/__init__.py`
  imports; unit and real-Postgres tests; the existing assertions that list tables, foreign keys and relationships; docs.
- **out (explicit):** Alembic and `CREATE TYPE` migrations (2.4); the `schema.prisma` parity diff (2.5); upload, download and notifier routes, services and
  schemas (packages 8, 9); any use of `FileType` in logic; writing to `DeletedHistory` or `Migration` (no code does it yet); file-size or mime validation;
  a new dependency.

## Acceptance criteria
- [ ] AC1 Given `import app.models`, then `Base.metadata.tables` also holds `File`, `Notification`, `NotificationRecipient`, `DeletedHistory`, `Migration`, with the
  Prisma column names, types, nullability and defaults of the final DDL (`File.content` is `BYTEA` and nullable, `File.size` is `INTEGER NOT NULL DEFAULT 0`).
- [ ] AC2 Given the metadata, then the indexes and keys are exactly Prisma's: `File_createdAt_mimeType_idx` (`createdAt DESC, mimeType`),
  `DeletedHistory_relationId_idx`, primary keys `<Table>_pkey` (`NotificationRecipient` composite `notificationId, accountId`), and no other index or unique on the five tables.
- [ ] AC3 Given the foreign keys, then they carry Prisma's actions: `AccountProfile_avatarId_fkey` `ON DELETE SET NULL`; `File_createdById_fkey`,
  `NotificationRecipient_notificationId_fkey` and `NotificationRecipient_accountId_fkey` `ON DELETE RESTRICT`; all `ON UPDATE CASCADE`.
- [ ] AC4 Given a real Postgres, when the tables are created from the metadata, then `pg_indexes`, `pg_constraint` and `pg_type` show the AC2 and AC3 objects, including the `FileType` type.
- [ ] AC5 Given the relationships, then `configure_mappers()` passes and the names are `File.created_by`, `File.account_profiles`; `Account.files`,
  `Account.notification_recipients`; `AccountProfile.avatar`; `Notification.notification_recipients`; `NotificationRecipient.notification`, `.account`, each pair linked both ways.
- [ ] AC6 Given one account with a file set as its profile avatar and one notification sent to it, when inserted and read back on a real Postgres, then `AccountProfile.avatar`
  loads the file with its bytes, `Account.files` and `Account.notification_recipients` load, and `updatedAt` is set; a file naming a missing creator, an avatar naming a missing file, a recipient
  naming a missing notification or account, and a second recipient row for the same pair are each refused by the database.
- [ ] AC7 `uv run mypy` (strict), ruff and the unit suite pass; the set in `tests/unit/test_db_base.py` lists all ten tables.
- [ ] AC8 Docs match: ARCHITECTURE, DOMAIN_GLOSSARY.

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| `FileType` is declared in Prisma but no column uses it | the enum exists as a Python `StrEnum` and as a Postgres type; no column | Q1 |
| `DeletedHistory.deletedAt` is `BOOLEAN` in the DDL (a name that suggests a timestamp) | kept for parity, like `dataOfBirth`; Python attribute `deleted_at`, a comment says it is a flag | Prisma DDL (ADR-0004) |
| `DeletedHistory` and `Migration` have no `deleted` column | none added; they are bookkeeping tables, not domain tables, and nothing here deletes from them (P6) | Prisma DDL |
| `Migration.createdAt` is nullable (`DEFAULT CURRENT_TIMESTAMP`, no `NOT NULL`) | `TimestampMixin` is `NOT NULL`, so the two columns are declared on the model | Prisma DDL |
| `File.content` is large | a plain nullable `LargeBinary` column, not deferred; every `select(File)` loads it, so services pick columns (`load_only`) in 8.x | Q2 |
| `Notification.type` is a free string (`// todo: move to enum` in Prisma) | `Text`, no enum | Prisma DDL |
| Column order differs from the migration (`content` was added last) | not asserted; the parity diff of 2.5 compares names and types | Q4 |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| Q1 | `FileType` has no column. Does the Postgres type still get created? | Yes: `Enum(FileType, name="FileType", metadata=Base.metadata)` so `create_all` and Alembic 2.4 see it and the parity diff of 2.5 stays empty. Glossary says it is unused; do not rely on it. | confirm |
| Q2 | Defer `File.content` so listing files does not load bytes? | No: parity and simplicity first; async code cannot lazy-load a deferred column, so it would need `undefer` everywhere. Revisit in 8.x. | confirm |
| Q3 | The scope row names `system.py`, which is not in `models/` today or in `project-structure.md` (`file.py` and `notification.py` only). | Create `app/models/system.py` as the row says (rule 2 of that file: a task may name extra files). The rule file lives under `.claude/**` (ask first), so this PR does not edit it; the human decides whether to. | **yes** |
| Q4 | Match the Prisma column order (`content` last)? | No, declaration order follows the mixins; names and types are the contract. | confirm |
| Q5 | Tests that already list tables, foreign keys, indexes and relationships (`tests/unit/test_db_base.py`, `tests/unit/test_account_models.py` and `tests/e2e/test_db_account_models.py`, whose `INDEX_DEFINITIONS` and `FOREIGN_KEY_ACTIONS` are asserted as exact equality over a whole-metadata `create_all`) must grow. | Extend each set with the new entries in the same commit as the code that adds them; nothing is removed or loosened (rule B3: an extension, but it edits existing assertions). | **yes**, B3 |
| Q6 | Real-Postgres tests: extend `tests/e2e/test_db_account_models.py` or add a file? | Add `tests/e2e/test_db_file_models.py` (the `test_db_*` pattern), same throwaway-schema fixture copied, since task 3.1 replaces both fixtures. | confirm |
