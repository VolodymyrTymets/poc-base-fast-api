# POC-2.2 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     Approving confirms the assumed answers in spec.md (edit them first to change one), in particular Q1 (the avatar foreign key and
     the three File/Notification relationships move to 2.3) and Q6 (an existing 2.1 assertion is replaced, rule B3). Format:
     Approved-by: <name> · <date> -->
Approved-by: volodymyr · 2026-10-31

**Revised after approval, on the human's instructions (what was built is in `spec.md`; where the text below still says otherwise, this note wins):**
1. `AccountProfile` has no `SSN` or `is18YearOld` column, and log/Sentry redaction no longer special-cases SSN: [ADR-0015](../../decisions/ADR-0015-drop-ssn-and-is18yearold.md).
2. Relationship attributes are snake_case with plural collections, following SQLAlchemy convention, not Prisma's PascalCase (scope-doc row 2.2 said "PascalCase relationships (P1)"): [ADR-0016](../../decisions/ADR-0016-snake-case-relationship-names.md). With that, no string targets and no `foreign_keys=` were needed.
3. The real-Postgres test file is `tests/e2e/test_db_account_models.py`.

Pattern followed: `app/core/db.py` (the mixins and naming convention were built for these tables, ADR-0014) with `tests/unit/test_db_base.py`
(DDL compiled for the postgresql dialect, no database) and `tests/e2e/test_db_mixins.py` (real Postgres, tables made and dropped around the test).
Layer: `models/` (ADR-0011: imports only `core` and sibling models). No Python precedent exists for relationships, so their mechanics are library
facts checked with Context7 (rule D4) before use: `relationship(back_populates=, foreign_keys=)` with `Mapped["X | None"]`, `Index(..., unique=True)`
with a `desc()` column, `sqlalchemy.Enum(StrEnum, name=...)`, composite primary key, `ForeignKey(ondelete=, onupdate=)`, `schema_translate_map`.

## Contract changes
- boundary: none (no route, schema or setting).
- data: model definitions only; no table is created in any real database until Alembic (2.4). They are the target 2.5 diffs against Prisma.
  Rollback is deleting the files' contents. `Base.metadata` goes from empty to five tables, which Alembic (2.4) will read.
- cross-task: 2.3 inherits the avatar foreign key and three relationships (Q1) and edits `account.py` and `account_profile.py`; the scope row lists neither file.
- generated output: none. No dependency added (`pyproject.toml` and `uv.lock` untouched).

## Requirements (ordered, one commit each; branch `feat/POC-2.2-account-models`, one draft PR)

### R1 — Tables, keys, indexes, foreign keys, enum (M)
- files: `app/models/account_role.py` (`AccountRoleType`, `AccountRole`, `AccountOnRole`), `app/models/account.py` (`Account`, `AccountIdentity`),
  `app/models/account_profile.py` (`AccountProfile`), `app/models/__init__.py` (change: import the three modules so the metadata lists them),
  `tests/unit/test_account_models.py` (new), `tests/unit/test_db_base.py` (change: line 58 only, Q6: the empty-metadata assertion becomes an exact set equality with the five `app.models` tables, with a `WHY:` comment, so it still fails if a scratch test model lands on the real `Base`; task 2.3 will extend that set).
- layer: models. Mixins per ADR-0014, chosen per Prisma model: `Account` takes Id, Timestamp, SoftDelete; `AccountRole`, `AccountIdentity`,
  `AccountProfile` take Id, SoftDelete; `AccountOnRole` takes SoftDelete and a composite primary key (`roleId`, `accountId`). `lastLoginAt` is
  `TIMESTAMP(3)` not null, no default. Uniques are `Index(<Table>_<col>_key, ..., unique=True)` (Prisma emits unique indexes, not constraints) and
  `Account_createdAt_idx` is `createdAt DESC`; index names are written out because the 2.1 convention would give `_idx` to a unique. Foreign keys
  carry `ondelete`/`onupdate` per AC3. `avatarId` is a plain `text` column (Q1). Python `#` comments (rule D6, never the SQL `comment=` argument, which would emit `COMMENT ON COLUMN` and show up in the 2.5 `pg_dump` diff) say why `dataOfBirth` keeps its name, and that
  `refreshToken` holds a sha256 (P5). No `__repr__`.
- test: table-driven against the Prisma DDL, no database: the table set; for each table the column names, `TEXT`/`TIMESTAMP(3)`/`BOOLEAN`/enum types,
  nullability and server defaults; primary keys; every index name, columns, uniqueness and `DESC`; foreign-key targets and actions; enum values
  `CUSTOMER`, `ADMIN`; `CreateTable` and `CreateIndex` compile for postgresql with quoted names; the replaced Q6 assertion.
- executed how: `uv run python -I -c` printing the compiled `CreateTable`/`CreateIndex` statements for the five tables, read against `migration.sql`.
- risk: `Index` with `desc()` and an explicit name under the naming convention (checked by the compiled-DDL test).

### R2 — Relationships (M)
- files: the three model files (change: relationships), `tests/unit/test_account_models.py` (change: add).
- layer: models. `TYPE_CHECKING` imports for the annotations, no import cycle between the three files. Relationship names are snake_case (ADR-0016); `Account.last_account_role` and `AccountRole.last_role_accounts`
  needed no `foreign_keys=` (one direct foreign key between the two tables); `AccountOnRole` links both sides by their own foreign key. No relationship to
  `File` or `Notification*` (Q1). `lazy` stays the default; callers choose `selectinload`, since async code cannot lazy-load.
- test: `configure_mappers()` passes; the relationship names of AC5 per class; `back_populates` pairs; two in-memory objects link both ways (no database).
- executed how: `uv run python -I -c "from sqlalchemy.orm import configure_mappers; import app.models; configure_mappers()"` and print each class's relationship keys.
- risk: ambiguous join paths between `Account` and `AccountRole` (SQLAlchemy raises at configure; the test is the experiment).

### R3 — Real-Postgres test (M)
- files: `tests/e2e/test_db_account_models.py` (new). Uses the existing `database_url` fixture from `tests/conftest.py`, so it needs `TEST_DATABASE_URL`.
- layer: tests (rule P8, no mocked database). First step, before any table exists: a small experiment shows whether the `AccountRoleType` enum follows `schema_translate_map` (Q5), so the path is known. A fixture then creates the enum and tables in a throwaway schema and drops only that schema. The fallback never runs `drop_all` against tables it did not create: if `"Account"` already exists in the target database the fixture calls `pytest.fail`, and using any other path stops and asks the human (rule C4).
- test: AC4, `pg_indexes.indexdef` and `pg_constraint` (`confdeltype`, `confupdtype`) match AC2 and AC3; AC6, one account graph inserted and read back with `selectinload`,
  `updatedAt` set; the unique and foreign-key refusals as `IntegrityError`, one test per refusal (parametrised).
- executed how: `uv run pytest tests/e2e/test_db_account_models.py -v` with `TEST_DATABASE_URL` read from `.env.test` (copy of `.env.test.example`, per `docs/RUNBOOK.md`), which must name a scratch database, never the server's default `postgres` database; the database name is checked with the human before the first run, and the output goes in the PR. The local Postgres may lack PostGIS; these tables do not need it.
- risk: the enum type may not follow `schema_translate_map` (fallback in Q5, stated in the PR).

### R4 — Docs and final gate (S)
- files: `docs/ARCHITECTURE.md` (Current: five models, `Base.metadata` lists them, relationships and the avatar column; Planned: 2.3 adds the avatar foreign key),
  `docs/DOMAIN_GLOSSARY.md` (Python identifiers now decided, relationship naming line, the `dataOfBirth` note), `docs/features/POC-2.2/spec.md` (ACs ticked).
- test: the whole command map once on the final tree: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest tests/unit`,
  `uv run pytest tests/e2e` with `TEST_DATABASE_URL`, `uv build`; `git diff --stat main` shows only the listed files.
- executed how: the R3 run plus the command map output, pasted into the PR.

## Docs to update in this PR
- [ ] docs/features/POC-2.2/spec.md (acceptance criteria checked off)
- [ ] docs/ARCHITECTURE.md — structural: `Base.metadata` is no longer empty
- [ ] docs/DOMAIN_GLOSSARY.md — identifiers and the relationship-naming line
- [ ] docs/decisions/ADR — ADR-0015 (drop `SSN`/`is18YearOld`) and ADR-0016 (snake_case relationships), both added after approval; snake_case column attributes over quoted names is the 2.1 pattern (ADR-0014)
- scope doc (Claude Docs), corrected on 2026-10-31 at the human's request: rows 1.6, 2.2, 2.3 (the avatar foreign key and relationships, Q1), 2.4, 2.5 and 5.4, plus a dated note at the top. Still the human's: the row 2.2 status

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| A column type or default differs from Prisma | parity diff in 2.5 | R1's table-driven test and R3's `pg_indexes` read, both written from the Prisma DDL |
| Unique declared as a constraint, not a unique index | `pg_dump` diff in 2.5 | AC2 asserts `Index(unique=True)` and R3 reads `indexdef` |
| Q1 is rejected (the human wants the avatar foreign key now) | `File` has to exist first: reorder 2.3 before 2.2, or add a stub | answer Q1 before approving |
| The Q6 edit is read as weakening a check | B3 | the replacement still asserts something real; the human approves it with the plan |
| A real `"Account"` table in the test database | data loss | throwaway schema (Q5); RUNBOOK already says to use a scratch database |

## Assumptions
- The open questions in spec.md hold as written; `Approved-by:` confirms Q1 and Q6.
- No new runtime dependency; `pyproject.toml` is untouched. CI and `.claude/` are not touched.
- Estimate: R1 M, R2 M, R3 M, R4 S, about the scope doc's 4 h.
- Python is the interpreter `uv` selects from `.python-version` (3.14); system `python3` (3.9.6 here) is never used (T2).
