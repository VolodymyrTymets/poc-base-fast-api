# POC-8.1 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     Approved-by: <name> · <date> -->
Approved-by: Volodymyr · 2026-11-03 (approved in session, recorded by Claude at their instruction)

Pattern followed: `app/services/account_role.py` and `account.py` (ADR-0021: class over an `AsyncSession`, domain errors as exceptions, no commit); settings
like `cors_origins` in `app/config.py` (`NoDecode` + `BeforeValidator` for a comma list); error classes like `ForbiddenError` in `app/core/errors.py`; tests like
`tests/e2e/test_db_account_service.py` (service on `db_session`) and `tests/unit/test_config.py`. No new pattern, no ADR.

## Contract changes
- boundary: none. No route uses the service; `openapi.json` must not change (stale test confirms).
- config: two settings, `FILE_MAX_SIZE` and `FILE_ALLOWED_MIME_TYPES`, names fixed by D9 and already in `.env.example` and `.env.development.example`; no new runtime dependency.
- errors: one `AppError` subclass (413); no new `ErrorCode`.

## Requirements (ordered; branch `feat/POC-8.1-file-assert-service`, one draft PR, one commit each)

### R1 — Settings and the 413 error (S)
- files: `app/config.py` (`file_max_size: int = Field(default=10_485_760, gt=0)`; `file_allowed_mime_types` as `list[str]`, `NoDecode` + a parser that
  splits on commas, strips, lowercases, drops blanks, and a validator refusing an empty result; drop the "the files module (8.x) enforces" wording of the body-limit comment only if it
  turns false); `app/core/errors.py` (`PayloadTooLargeError(ValidationFailedError)`, `status_code = 413`, `default_message = "Payload too large"`);
  `.env.development.example` only if it lacks the two lines (check, do not assume); `docs/api/ERRORS.md` (name the class in the 413 bullet).
- layer: config, core.
- test: `tests/unit/test_config.py` (defaults, comma list, blank entries, empty list refused, `FILE_MAX_SIZE=0` refused, error text names the field not the value);
  `tests/unit/test_errors.py` and, per "Adding an error" step 3 of ERRORS.md, `tests/e2e/test_http_errors.py` (a route raising `PayloadTooLargeError` answers 413 with the standard body and code `VALIDATION_FAILED`).
- executed how: `uv run python -c` building `Settings()` with `FILE_ALLOWED_MIME_TYPES=" Image/PNG, ,image/jpeg"` and printing the two fields; the unit run.
- risk: the 413 class and the middleware's 413 share a status; the handler keys on the class, not the status (read `register_error_handlers` first).

### R2 — FileAssertService (M)
- files: `app/services/file_assert.py`: `FileAssertService(session, settings)`; `assert_upload(size: int, mime_type: str | None) -> None` raising
  `PayloadTooLargeError` or `ValidationFailedError` with `details=[{"in": "body", "field": "file", "message": ..., "type": ...}]` (types `file_too_large`, `file_type_not_allowed`);
  `async get_owned_file(file_id, account_id) -> File` with `select(File).options(load_only(...))` over every column but `content`, filtering `created_by_id`
  and `deleted` false, `ForbiddenError` when there is no row. Docstring says `content` is not loaded and must not be touched (async lazy load fails).
- layer: services (imports `app.models`, `app.core`, `app.config`; no FastAPI).
- test: `tests/e2e/test_db_file_assert_service.py` on `db_session` (real Postgres, rule P8): AC3, AC4 (unknown, other account, soft-deleted), a file saved with bytes whose
  `content` stays unloaded (`session.expunge_all()` between the insert and `get_owned_file`, because an object already in the identity map keeps its loaded `content`; then `"content" in inspect(file).unloaded`); `tests/unit/test_file_assert_service.py` (no database: `FileAssertService(AsyncSession(), settings).assert_upload(...)`, an unbound `AsyncSession` does no I/O until a query runs): AC1 (limit and limit+1), AC2 (case, parameters, `None`, empty string), AC6 (`str(error)` and `details` hold no input).
- executed how (evidence): scratchpad script with its own scratch database (Docker `postgis/postgis:16-3.4` on a free port, `DATABASE_URL` exported, never `.env`),
  `alembic upgrade head`, create two accounts and a file through the models, call `get_owned_file` as owner, other account, soft-deleted, and `assert_upload` at both limits; paste the output.
- risk: `load_only` with the `Index` on `createdAt` is irrelevant; confirm `inspect(file).unloaded` works on the async session's object (cheapest check: the e2e test).

## Node spec port (`poc-base/api/src/files/services/file-assert.service.spec.ts`, 8 cases)
| Node case | Here |
|-----------|------|
| assertFileInput: accepts content within the limit, allowed mime | `test_file_assert_service.py`: size at the limit and an allowed type pass (AC1, AC2) |
| rejects decoded content larger than FILE_MAX_SIZE | same file: limit+1 raises 413 (AC1); size is the received byte count (decision 10) |
| rejects content with no mimeType | same file: `None` and `""` raise 422 (AC2) |
| accepts a missing content field | does not apply: `POST /files` requires the bytes (ENDPOINTS decision 10); no content means no `assert_upload` call, a rename-only `PATCH` is the router's (8.2) |
| assertUpdateFile: rejects a non-owner | `test_db_file_assert_service.py`: another account's file raises `ForbiddenError` (AC4) |
| falls back to the stored mimeType when content is sent without one | does not apply: a multipart part carries its own type, so there is nothing to fall back to (decision 10); a missing type is 422 |
| still rejects content with no mimeType anywhere | covered by the 422 case above |
| assertFileAccessByAccount: rejects a non-owner | `test_db_file_assert_service.py`: the same test (AC4) |
New here, not in Node: unknown id and soft-deleted file are 403 (Node let a deleted file through, rule P6); case-insensitive type match.

## Done check (rule B1)
`uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest tests/unit`, `uv run pytest tests/e2e`, `uv run python -m app.cli --export-openapi --check`.
All ported cases above pass. Anything not run goes under "Not verified".

## Docs to update in this PR (rule E1)
- [x] docs/features/POC-8.1/spec.md (ACs checked off)
- [x] docs/ARCHITECTURE.md: `services/file_assert.py` built; the two settings; `PayloadTooLargeError` in the `core/errors.py` row
- [x] docs/api/ERRORS.md: the 413 bullet names the class and that the upload limit is `FILE_MAX_SIZE`
- [x] docs/RUNBOOK.md: `FILE_MAX_SIZE` and `FILE_ALLOWED_MIME_TYPES` in the settings paragraph
- [x] docs/DOMAIN_GLOSSARY.md: no new term; docs/decisions: none

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| A caller reads `file.content` on a `load_only` file | `MissingGreenlet` 500 | the e2e test asserts `content` is unloaded; the docstring says so |
| Declared mime type is client-controlled | a renamed file passes | out of scope (as in Node); stated in the PR |
| `FILE_MAX_SIZE` above `MAX_REQUEST_BODY_BYTES` | the middleware answers 413 first; harmless | note in RUNBOOK |

## Estimate
R1 S, R2 M.

## Assumptions
Q1 to Q3 of the spec. Ownership is by creator only. The caller owns the transaction.

## Not covered
Routes, multipart, storing files, streaming, the avatar update, content sniffing.
