# POC-2.3 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     Approving confirms the assumed answers in spec.md (edit them first to change one), in particular Q3 (`system.py`, rule file untouched)
     and Q5 (existing table, foreign-key and relationship assertions are extended, rule B3). Format:
     Approved-by: <name> · <date> -->
Approved-by: volodymyr · 2026-10-31

Pattern followed: `app/models/account.py`, `account_role.py` and `account_profile.py` (2.2: mixins per Prisma model, written-out index names, snake_case
attributes over quoted columns, `TYPE_CHECKING` imports for relationships, ADR-0014 and ADR-0016), tested like `tests/unit/test_account_models.py`
(table-driven against the Prisma DDL, no database) and `tests/e2e/test_db_account_models.py` (real Postgres, throwaway schema).
Layer: `models/` (ADR-0011: imports only `core` and sibling models). No precedent exists for `LargeBinary` or an enum with no column: both are
library facts checked with Context7 (rule D4) before use: `sqlalchemy.LargeBinary` on PostgreSQL gives `BYTEA`; `Enum(..., metadata=)` creates the type on `create_all`.

## Contract changes
- boundary: none (no route, schema or setting).
- data: model definitions only; no table exists in a real database until Alembic (2.4). `AccountProfile.avatar_id` gains a foreign key (model only). Rollback is reverting the commits.
- cross-task: `AccountProfile` and `Account` get new attributes (`avatar`, `files`, `notification_recipients`); no caller exists yet. 2.4 reads the metadata.
- generated output: none. `pyproject.toml` and `uv.lock` untouched.

## Requirements (ordered, one commit each; branch `feat/POC-2.3-file-notification-models`, one draft PR)

### R1 — `File`, `FileType`, the avatar foreign key (M)
- files: `app/models/file.py` (new content: `FileType`, `File`), `app/models/account_profile.py` (change: `ForeignKey("File.id", ondelete="SET NULL", onupdate="CASCADE")`, `avatar`),
  `app/models/account.py` (change: `files`), `app/models/__init__.py` (change: import), `tests/unit/test_file_models.py` (new),
  `tests/unit/test_db_base.py` and `tests/unit/test_account_models.py` (change: add `File` / the new foreign keys and relationships to their sets, Q5),
  `tests/e2e/test_db_account_models.py` (change, Q5: it runs `create_all` over the whole metadata and asserts `INDEX_DEFINITIONS` and `FOREIGN_KEY_ACTIONS` are exactly equal, so each requirement
  grows both with the objects it adds; the query is not narrowed to `Account%`, which would weaken it, rule B3).
- layer: models. `File` takes Id, Timestamp, SoftDelete; `size` is `Integer`, default 0 and `server_default`; `content` is `LargeBinary`, nullable; `File_createdAt_mimeType_idx` is
  `Index(..., File.created_at.desc(), File.mime_type)` declared after the class, as `Account_createdAt_idx` is; `File.created_by` / `Account.files` and `File.account_profiles` / `AccountProfile.avatar`
  with `back_populates`. The stale comment above `avatar_id` is replaced by the real reason (rule D6).
- test: the 2.2 table-driven checks for `File`: columns, types (`BYTEA`, `INTEGER`), defaults, key, index with `DESC`, the two foreign keys and their actions, `FileType` values `IMG`, `VIDEO` and the type name,
  `CreateTable` compiles quoted; `configure_mappers()` and the relationship pairs; the extended sets still fail on a table or foreign key nobody listed.
- executed how: `uv run python -I -c` printing `CreateTable(File)` and the `CreateIndex` for the postgresql dialect and `configure_mappers()` over `app.models`, read against `migration.sql` of the four Node migrations.
  Then, before R2, the riskiest unknown: `uv run pytest tests/e2e/test_db_account_models.py` (needs the scratch `TEST_DATABASE_URL`, confirmed with the human first) plus a one-query `pg_type` read inside that schema showing `FileType` was created under `schema_translate_map`.
- risk: `Enum(metadata=)` with the naming convention, and a `File`/`AccountProfile` foreign-key cycle in `create_all` (none: `File` -> `Account` only; checked by the e2e fixture in R4, cheaply by `sorted_tables` in R1's test).

### R2 — `Notification`, `NotificationRecipient` (S)
- files: `app/models/notification.py` (new content), `app/models/account.py` (change: `notification_recipients`), `app/models/__init__.py`, `tests/unit/test_notification_models.py` (new),
  `tests/unit/test_db_base.py`, `tests/unit/test_account_models.py`, `tests/e2e/test_db_account_models.py` (change: sets, Q5).
- layer: models. `Notification` takes Id, Timestamp, SoftDelete; `message` and `type` are `Text` not null; `NotificationRecipient` takes SoftDelete and the composite key
  (`notificationId`, `accountId`) like `AccountOnRole`; no index beyond the key (Prisma has none).
- test: columns, key, the two foreign keys (`RESTRICT`/`CASCADE`), relationship pairs, no unlisted index.
- executed how: the same `-I -c` print and `configure_mappers()`.
- risk: none.

### R3 — `DeletedHistory`, `Migration` in `system.py` (S)
- files: `app/models/system.py` (new), `app/models/__init__.py`, `tests/unit/test_system_models.py` (new), `tests/unit/test_db_base.py` (set), `tests/e2e/test_db_account_models.py` (change: `INDEX_DEFINITIONS`, Q5).
- layer: models. `DeletedHistory`: IdMixin only, `relation_id` text not null, `deleted_by` text nullable, `deleted_at` boolean not null (comment: a flag despite the name, kept for parity); `DeletedHistory_relationId_idx`.
  `Migration`: IdMixin, `name` not null, `successful` default false, nullable `result` / `description`, `created_at` nullable with `server_default CURRENT_TIMESTAMP`, nullable `updated_at` set by the app (as `TimestampMixin.updated_at` does; declared by hand because the mixin's `created_at` is not null).
  Neither has `deleted` (spec edge case).
- test: columns, nullability, defaults, the index, no foreign key, compiled DDL.
- executed how: the `-I -c` print of both `CreateTable` statements.
- risk: `updated_at` onupdate behaviour must match the mixin; the test asserts the same `onupdate` is present.

### R4 — Real-Postgres test (M)
- files: `tests/e2e/test_db_file_models.py` (new). Uses `database_url` from `tests/conftest.py` (needs `TEST_DATABASE_URL`).
- layer: tests (rule P8). Throwaway schema per test as in `test_db_account_models.py`; fails, never drops, when `"File"`, `"Notification%"` or the `FileType` type already exists outside its own schemas (rule C4).
- test: asserts only its own objects, not the whole schema again (the whole-schema equality stays in `test_db_account_models.py`, testing.md rule 2): AC4 (`pg_indexes.indexdef`, `pg_constraint` actions, `pg_type` has `FileType` with `IMG`, `VIDEO`); AC6 round trip with `selectinload` (`avatar`, `files`, `notification_recipients`, bytes equal), `updatedAt` set;
  one parametrised `IntegrityError` test per refusal.
- executed how: `uv run pytest tests/e2e/test_db_file_models.py -v` with a scratch database named in `.env.test`, never the server's default `postgres`; the database name is confirmed with the human before the first run (the same constraint as 2.2). Output goes in the PR.
- risk: the two e2e files both guard against leftover `Account*` objects of the other's schema; the guards exclude only their own prefix, so a crashed run of one blocks the other until its schema is dropped. The failure message names the schema.

### R5 — Docs and final gate (S)
- files: `docs/ARCHITECTURE.md`, `docs/DOMAIN_GLOSSARY.md`, `docs/features/POC-2.3/spec.md` (ACs ticked).
- test: the command map once on the final tree: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest tests/unit`, `uv run pytest tests/e2e` (with `TEST_DATABASE_URL`), `uv build`; `git diff --stat main` shows only the listed files.
- executed how: the R4 run plus the command-map output, pasted into the PR.

## Docs to update in this PR
- [ ] docs/features/POC-2.3/spec.md (acceptance criteria checked off)
- [ ] docs/ARCHITECTURE.md — "Where data truth lives" (ten tables, avatar FK now exists), repo-layout row (`system.py`), delete the 2.3 bullet under Planned
- [ ] docs/DOMAIN_GLOSSARY.md — `File` / `FileType` status, `DeletedHistory`, `Migration` (new terms), naming line for the new relationships, the `deletedAt` flag note
- [ ] docs/decisions — no ADR: no new pattern (Q1 is a detail of ADR-0004's parity target); `.claude/rules/project-structure.md` says `file.py` and `notification.py` only — a human decides whether to add `system.py` (Q3)
- scope doc (Claude Docs): row 2.3 status is the human's

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| A type or default differs from the final Node DDL (four migrations, not just init) | parity diff in 2.5 | tests written from the summed DDL; R4 reads `pg_indexes` |
| `Enum(metadata=)` does not emit `FileType` under `schema_translate_map` | AC4 fails | end of R1: one experiment query on `pg_type`; fallback is stated in the PR, never `drop_all` on a shared database |
| Extended assertions read as weakening a check (Q5) | rule B3 | the human approves with the plan; every set only grows |
| `File.content` loaded by every file query | slow lists later | out of scope here; noted in the glossary for 8.x |

## Assumptions
- The open questions in spec.md hold as written; `Approved-by:` confirms Q3 and Q5.
- No new runtime dependency; CI and `.claude/` are not touched.
- Estimate: R1 M, R2 S, R3 S, R4 M, R5 S, about the scope doc's 3 h.
- Python is the interpreter `uv` selects from `.python-version` (3.14), never system `python3` (T2).
