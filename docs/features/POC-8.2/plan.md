# POC-8.2 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     Approved-by: <name> · <date> -->
Approved-by: Volodymyr · 2026-11-09 (approved in session, recorded by Claude at their instruction)

Pattern followed: `app/routers/account_profile.py` + `app/services/account_profile.py` + `get_account_profile_service` in `app/dependencies.py` (ADR-0021 service that
flushes, route owns the commit; ADR-0025 one provider per service; `require_roles` then ownership in the service, rule P7). Tests like
`tests/integration/http/test_http_account_profile.py` and `tests/integration/db/test_db_file_assert_service.py`. No new pattern, no ADR.

## Contract changes
- boundary: three new routes (additive), the first multipart ones; `openapi.json` changes. No consumer yet (no `web/`).
- dependency: `python-multipart` (runtime), **approved by Volodymyr on 2026-11-09 (rule C2, question Q1); this approves the dependency only, not the plan.** Without it `UploadFile`/`Form` fail when the route is declared.
- data: none; `File` table and columns exist (task 2.3). Reads use `defer(File.content, raiseload=True)` as `get_owned_file` does.
- generated output: `uv run python -m app.cli --export-openapi` (never hand-edited).

## Requirements (ordered; branch `feat/POC-8.2-file-routes`, one draft PR, one commit each)

### R1 — Dependency and response model (S)
- files: `pyproject.toml` + `uv.lock` (via `uv add python-multipart`, after approval), `app/schemas/files.py` (`FileResponse`: camelCase like `AccountProfileResponse`,
  `content_url` computed from the id, no `content` field; `FileName = Annotated[str, StringConstraints(max_length=255)]`)
- layer: schemas
- test: `tests/unit/test_file_schemas.py` — wire names, `contentUrl` is `/api/v1/files/{id}/content`, the model has no bytes field, a 256-char name is rejected
- executed how: `uv run pytest tests/unit/test_file_schemas.py`; `uv run python -c "import python_multipart"`
- risk: the lockfile change is made only by `uv` (rule T3)

### R2 — `FilesService` and provider (M)
- files: `app/services/files.py` (filename fallback goes through the `FileName` limits, else `null`; `FilesService(session, file_assert)`: `create(account_id, upload_bytes, mime_type, filename, name)`, `update(file_id, account_id, ...)`,
  `get(file_id, account_id)`; calls `assert_upload` before any write; `update` loads the row with `get_owned_file`, then sets name, and bytes/size/mime together when a file is sent; flush, never commit),
  `app/dependencies.py` (`get_files_service`, built on `get_session` and `get_file_assert_service`)
- layer: services, dependencies
- test: `tests/integration/db/test_db_files_service.py` on `db_session` (real Postgres, rule P8), only what is new in the service (ownership and limit rules are 8.1's, testing rule 2): a failed check stores nothing;
  create stores bytes, size from bytes, name fallback (long or control-character filename gives `null`); update name-only keeps bytes, update with file replaces all three; `get` does not load `content`.
  `tests/unit/test_routers_use_service_providers.py` must still pass (the provider rule).
- executed how: run the integration file; a small script against the test DB is not needed, R3 executes it over HTTP
- risk: `update` after `get_owned_file` has `content` deferred with `raiseload`; assigning `content` on it must not trigger a load. Cheapest check: the replace-content test.

### R3 — Routes (M)
- files: `app/routers/files.py` (`POST ""` 201, `PATCH "/{id}"`, `GET "/{id}"`; `file: UploadFile`, `name: Annotated[str | None, Form(max_length=255)]`;
  `Depends(require_roles(ADMIN, CUSTOMER))`, service, `get_session` for the commit; `response_model=FileResponse`; reads the bytes and passes their length to `assert_upload` (FastAPI has already parsed the form before the handler, so the memory bound is the 12 MiB body middleware, not this read)),
  `openapi.json` (regenerated), `docs/api/ENDPOINTS.md` (rows marked built)
- layer: routers
- test: `tests/integration/http/test_http_files.py` — AC1 to AC7 over `client` with the auth helper: 201 shape, 401, missing file 422, bad type 422, 413 over limit, PATCH name-only and replace, 403 for another account / unknown id, GET has no bytes,
  the uploaded id accepted as `avatarId`; `name=""` falls back to the filename; a duplicated part, last wins; a 0-byte part with an empty filename is 422; the 403 and 413/422 status and error bodies live here only; `tests/unit/test_openapi_stale.py` passes
- executed how: run the app against the compose or local Postgres, sign up, `curl -F file=@x.png -F name=a http://localhost:3001/api/v1/files` with the Bearer token, then PATCH and GET; paste request and response in the PR (rule B5)
- risk: FastAPI's 422 for a missing form part must use the error contract (`VALIDATION_FAILED`, `details`); checked by the missing-file test

## Docs to update in this PR
- [x] docs/features/POC-8.2/spec.md (acceptance criteria checked off)
- [x] docs/ARCHITECTURE.md — `services/files.py` and `routers/files.py` built, `get_files_service` in the provider list, three more routes, `python-multipart` in the dependency list, Planned section
- [x] docs/RUNBOOK.md — a "Files" section with the curl calls; limits text names the routes
- [x] docs/api/ENDPOINTS.md — `createFile`, `updateFile`, `file` marked built; Roles column `ADMIN` or `CUSTOMER` (owner); name fallback (new, not from Node), mime normalisation, duplicate parts, empty `name`
- [x] .claude/rules/api-rest.md rule 10 — the "Note for task 8.2" is settled (ask-first path, `.claude/**`)
- [x] docs/BUSINESS_MODEL.md and the ARCHITECTURE status line — 8.2 built, 11.6 already merged (#43): stale text fixed here (rule E2)
- [x] docs/DOMAIN_GLOSSARY.md — only if a term is new (`contentUrl`); likely one line
- [x] CLAUDE.md / ADR: none (no new pattern)

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| `python-multipart` not approved | routes cannot take multipart; plan blocked | Q1, answered before R1 |
| Whole upload held in memory (up to 12 MiB through the body limit) | memory per request | read `max_size + 1` bytes only; the 12 MiB middleware cap bounds it; no test needed beyond the 413 case |
| 8.1's `get_owned_file` returns a row with `content` raising on access | `update` crashes when replacing bytes | the replace-content test in R2 |
| Form validation errors use FastAPI's default shape | breaks the error contract | the missing-file and long-name tests assert the `{"error": ...}` body |

## Assumptions
- Q2 to Q4 of the spec; Q1 needs a human.
- The three routes accept the roles `ADMIN` and `CUSTOMER` like 5.4 and keep all three layers of rule P7 (ADR-0022; ENDPOINTS decision 15 leaves the role choice to a human, so the choice is recorded in ENDPOINTS.md); ownership is in the service.
- `GET /files/{id}` and `PATCH` do not read the bytes (`defer`), so `contentUrl` works as the only way to the bytes once 8.3 lands.
