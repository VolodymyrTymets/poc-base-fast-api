# POC-8.3 — GET /api/v1/files/{id}/content

## Problem
An account can upload a file and read its metadata (task 8.2), but cannot get the bytes back: `contentUrl` in every file response points at a route that
does not exist. ADR-0009 moved the bytes out of JSON into an authenticated, owner-only download; ENDPOINTS.md maps it as the new route "`GET /files/{id}/content`".

## Goal / business value
Goal 1 (scaffolding: file storage in Postgres is only useful if the bytes can be read back) and goal 2 (the avatar a profile points at can finally be shown).

## Scope
- in: `FilesService.get_content`; `GET /api/v1/files/{id}/content` returning the bytes with `Content-Type` (the stored mime type), `Content-Length` and
  `X-Content-Type-Options: nosniff`; a named exemption for this route in `tests/unit/test_response_models.py`; regenerated `openapi.json`.
- **out (explicit):** signed or public URLs and use in an `<img src>` (a client fetches a blob, ADR-0009), HTTP range requests, `ETag`/conditional requests,
  true streaming from the database (the value is read whole, ADR-0009), image resizing, deleting a file, `Content-Disposition` unless Q1 says otherwise.

## Acceptance criteria
- [ ] AC1 Given the owner's Bearer token, `GET /files/{id}/content` answers 200 with exactly the bytes that were uploaded, `Content-Type` equal to the stored mime type (for a `text/*` type Starlette appends `; charset=utf-8`; the default jpeg and png list has none), `Content-Length` equal to the byte count and `X-Content-Type-Options: nosniff`.
- [ ] AC2 After `PATCH` replaced the content, the route returns the new bytes with the new `Content-Type`.
- [ ] AC3 No token is 401 `UNAUTHORIZED`; an account with no role is 403; another account's file, an unknown id and a soft-deleted file are the same 403 `FORBIDDEN` (task 8.1, ENDPOINTS decision 3).
- [ ] AC4 A file row with no stored bytes (`content` is null, possible only for rows from Node's two-step upload) is 404 `NOT_FOUND` (ENDPOINTS decision 19), after the owner check.
- [ ] AC5 The route is read-only: it never commits and changes no row.
- [ ] AC6 An upload over `FILE_MAX_SIZE` is 413 (already 8.2; covered by its tests, not repeated here). `openapi.json` is regenerated, documents a binary 200 body and the 422/500 error body every route inherits (401, 403 and 404 are not documented per route, as on the other file routes), and the stale test passes.
- [ ] AC7 `tests/unit/test_response_models.py` still fails a route with no response model, except this one, which is named there with its reason.

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| Stored `mimeType` is null | `Content-Type: application/octet-stream` | assumption Q2 |
| 0-byte file (the upload allowed it) | 200 with an empty body and `Content-Length: 0` | 8.2 allows size 0 |
| HEAD request | not added; FastAPI does not answer HEAD for a GET route | assumption (out of scope) |
| File of a soft-deleted account that the caller owns | same as any owned live file; the route does not look at the account | 8.1 `get_owned_file` |
| Content larger than memory expectations | bounded by `FILE_MAX_SIZE` at upload (default 10 MB); a row from another source could be larger and is read whole | ADR-0009 |
| `Cache-Control` | `no-store` from the security-headers middleware, kept: the body is private | ADR-0033 |
| Whole body vs "chunked" | a `Response` with `Content-Length`, as ADR-0009 and the scope doc require; ADR-0009's word "chunked" is loose | assumption Q3 |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| Q1 | Send `Content-Disposition`? The stored type is the uploader's declared one, limited to `FILE_ALLOWED_MIME_TYPES` (jpeg and png by default); a fork that allows `text/html` would serve it inline under the API origin | No `Content-Disposition`; rely on the allowlist and `nosniff` (the ENDPOINTS row lists only those headers); record the fork risk in the RUNBOOK. A "yes" changes one header in the route, one assertion in the AC1 test and the ENDPOINTS and RUNBOOK lines; `Content-Security-Policy: sandbox` is another option besides `attachment` | **answered: default accepted by Volodymyr · 2026-11-09 (rule F2)** |
| Q2 | Type when `mimeType` is null | `application/octet-stream` | no |
| Q3 | `Response` with the whole value, not `StreamingResponse` | yes: the value is read from `bytea` whole (ADR-0009) and `Content-Length` must be set | no |
