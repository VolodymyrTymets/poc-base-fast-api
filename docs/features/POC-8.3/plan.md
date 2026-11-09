# POC-8.3 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     Approved-by: <name> · <date> -->
Approved-by: Volodymyr · 2026-11-09 (approved in session, recorded by Claude at their instruction; Q1 answered by approving the stated default: no `Content-Disposition`)

Pattern followed: `app/routers/files.py` + `app/services/files.py` + `get_files_service` from task 8.2 (guard order, provider, errors, tests on `module_database_url` with
`sign_up`); the byte-reading follows the docstring of `FileAssertService.get_owned_file` (task 8.1: "a caller that needs the bytes selects them itself (task 8.3)").
No precedent for a route that returns bytes: it needs no ADR, because ADR-0009 decides it; the one new thing is a named exemption in `test_response_models.py`, which that file's docstring reserves for this task.

## Contract changes
- boundary: one new route (additive), the first with a non-JSON 200 body; `contentUrl` of the 8.2 responses starts to resolve. `openapi.json` changes.
- data: none; read only. No new dependency, no new setting, no new error code (`NOT_FOUND` and `FORBIDDEN` exist).
- generated output: `uv run python -m app.cli --export-openapi`.

## Requirements (ordered; branch `feat/POC-8.3-file-content`, one draft PR, one commit each)

### R1 — `FilesService.get_content` (S)
- files: `app/services/files.py` (change: `FileContent` dataclass `(content: bytes, mime_type: str | None)` and `get_content(file_id, account_id)`: `get_owned_file` first (so a stranger and a
  soft-deleted file are `ForbiddenError`), then `select(File.content).where(File.id == file_id)`; `None` content raises `NotFoundError`; no flush, no write)
- layer: services
- test: `tests/integration/db/test_db_files_service.py` (change) — returns the stored bytes and mime type; after `update` with a new file returns the new ones; a row whose `content` is null
  raises `NotFoundError` (row made with `File(content=None)` on `db_session`); the owner check itself is 8.1's, not retested (testing.md 2)
- executed how: `uv run pytest tests/integration/db/test_db_files_service.py`; the HTTP run is R2
- risk: the bytes read after `get_owned_file` returns a row with `content` under `raiseload`; reading them by a separate `select` avoids touching that attribute. Checked by the first test.

### R2 — The route and its contract (M)
- files: `app/routers/files.py` (change: `@router.get("/{id}/content", response_class=Response, responses={200: {"content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}, "description": ...}})`, the 200 only: 422 and 500 are inherited from the app, 401/403/404 are not documented per route, as on the other file routes;
  same `Caller` guard and `FileId` as the other routes; returns `Response(content, media_type=mime or "application/octet-stream", headers={"X-Content-Type-Options": "nosniff"})`; no session dependency, so it cannot commit),
  `tests/unit/test_response_models.py` (change: `BYTE_ROUTES = {"/api/v1/files/{id}/content"}` skipped with a comment giving the reason; a new test that every path in the set exists in `create_app()` and is annotated to return a `Response`, so the exemption cannot outlive its route; "a route with no model is still flagged" is already tested by `/untyped`),
  `openapi.json` (regenerated)
- layer: routers, tests
- test: `tests/integration/http/test_http_files.py` (change) — AC1 upload then download: body equal, `Content-Type`, `Content-Length`, `nosniff`; AC2 replace then download; AC3 401 without a token and 403 for another account, unknown id
  (parametrized with the existing 403 test where it fits); AC4 404 for a row with null content (row inserted through `db_engine`); 0-byte file gives an empty body with `Content-Length: 0`; one assertion subject each, AAA labels
- executed how: the real server on a throwaway PostGIS (as in 8.2): sign up, `curl -F file=@x.png` then `curl -D - -o out.png localhost:3001/api/v1/files/$ID/content` and `cmp x.png out.png`; the same with another account's token (403) and no token (401); paste request, headers and `cmp` result in the PR
- evidence for the clauses with no new test (testing.md 2): AC3 no role is 403 by `require_roles`, tested in task 5.2 (`tests/integration/http/test_http_require_roles.py`); AC3 soft-deleted file is 403 in 8.1's `tests/integration/db/test_db_file_assert_service.py`; AC5 read-only holds because the route has no `get_session` dependency of its own and `get_content` never flushes (structural, listed under "Not verified" in the PR)
- risk: FastAPI must not try to serialise `Response` or add a JSON model: `response_class=Response` plus a `Response` return annotation; checked by the openapi export and the round-trip test.

## Docs to update in this PR
- [x] docs/features/POC-8.3/spec.md (acceptance criteria checked off)
- [x] docs/ARCHITECTURE.md — route count and the content route in "Boundaries and contracts"; remove the "Planned" file-content bullet and fix the status line (the file routes are done, only the cache is not); `FilesService.get_content`
- [x] docs/BUSINESS_MODEL.md — status line: the file routes are built
- [x] docs/api/ENDPOINTS.md — the `(new)` row marked built, with Roles `ADMIN` or `CUSTOMER` already set; decisions: whole body with `Content-Length`, null mime type, 404 for no content
- [x] docs/RUNBOOK.md — "Files": the download call, the `cmp` check, the inline-content risk of a widened allowlist (Q1)
- [x] docs/DOMAIN_GLOSSARY.md — the `contentUrl` row: it now answers
- [x] .claude/rules/api-rest.md rule 2 — names the exemption test; rule 12 unchanged
- [ ] ADR: none; ADR-0009 is followed as written (its word "chunked" is recorded in ENDPOINTS as a whole body with `Content-Length`)

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| Q1 unanswered: no `Content-Disposition` serves a widened allowlist's `text/html` inline | stored XSS on a fork that allows html | the human answers Q1 at approval; the default is documented in the RUNBOOK |
| The 200 is not JSON, so the exemption could hide a route that forgot its model | a leak of an ORM object through a future route | the exemption is one named path, and a test keeps flagging every other route without a model |
| A large file is read whole into memory | memory per request | bounded by `FILE_MAX_SIZE` at upload; stated in the RUNBOOK, as in ADR-0009 |
| `Response` skips the `response_model` filter | none here: the route returns bytes from one column and no ORM object | the round-trip test |

## Assumptions
- Spec Q2 and Q3; Q1 needs a human.
- ADR-0009 says "chunked" and the scope doc requires `Content-Length`; HTTP/1.1 allows only one. The route sends `Content-Length` and ENDPOINTS.md records it (no superseding ADR: the ADR's explicit requirement is `Content-Length`). The approval of this plan acknowledges that.
- 8.2 is merged (PR #44, `bec79cd` on `main`); the branch starts from it.
- The route takes the roles `ADMIN` or `CUSTOMER` like the other file routes (ADR-0022, ENDPOINTS.md "Built in task 8.2").

## Deviations (found while implementing, recorded here and in the PR)
- `tests/unit/test_response_models.py` (R2, unplanned): `test_every_route_has_a_response_model_that_is_not_an_orm_class` walked only `APIRoute` entries of `app.routes`. In FastAPI 0.162 an included router is one opaque entry there, so the check saw none of the feature routes and passed whatever they returned. The plan's claim that "`/untyped` already tests a route with no model" was true only for a route added straight to the app. The fix reads the routes of the included routers (`effective_route_contexts()`) so the `BYTE_ROUTES` exemption is real; every existing feature route passes under the new walk, and the exemption is keyed on `("GET", path)`. Without it AC7 would be vacuous.
- Review of the first draft: a test for the null mime type (`application/octet-stream`) was added; the service-level "replacement" test was dropped as a duplicate of the HTTP one.

