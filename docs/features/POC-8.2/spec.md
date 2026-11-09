# POC-8.2 — POST/PATCH/GET /api/v1/files

## Problem
A signed-in account cannot store a file. `FileAssertService` (8.1) checks size, type and ownership, and the `File` model holds the bytes in `bytea`, but no
route or `FilesService` writes or reads a File. Without it an avatar (`avatarId`, task 5.4) cannot be created. Node has `createFile`, `updateFile` and
`file` (`files/files.resolver.ts`, `files.service.ts`); ENDPOINTS.md (File endpoints) maps them to REST.

## Goal / business value
Goal 1 (scaffolding: file storage in Postgres is one of the pieces a POC would rebuild) and goal 2 (the avatar path completes the profile flow).

## Scope
- in: `FilesService` (`create`, `update`, `get`); `POST /api/v1/files` (multipart, 201), `PATCH /api/v1/files/{id}` (multipart, 200), `GET /api/v1/files/{id}`
  (metadata, 200); the response model `FileMetadataResponse` `{id, name, mimeType, size, createdAt, contentUrl}`; a `get_files_service` provider; regenerated `openapi.json`.
- **out (explicit):** `GET /files/{id}/content` (task 8.3; `contentUrl` is only the path, it resolves after 8.3), deleting a file, listing files, `FileType`
  (no column uses it), image content sniffing (the declared type is trusted, as in Node), virus scanning, rate limiting (issue I.8).

## Acceptance criteria
- [x] AC1 Given a Bearer token and a multipart `file` (png, under 10 MB) with an optional `name`, `POST /files` answers 201 with `{id, name, mimeType, size, createdAt, contentUrl}`; `size` is the received byte count; `contentUrl` is `/api/v1/files/{id}/content`; the bytes are stored in `File.content`.
- [x] AC2 Without `name` (or with an empty one: FastAPI treats `""` as missing), the stored name is the upload's filename when it fits `FileName` (at most 255 characters, no control characters), else `null` (assumption Q2); a `name` over 255 characters is 422.
- [x] AC3 No token is 401; a missing `file` part is 422; a disallowed mime type is 422 and an upload over `FILE_MAX_SIZE` is 413, both `VALIDATION_FAILED` with the field in `details` (via `FileAssertService.assert_upload`); nothing is stored in those cases.
- [x] AC4 `PATCH /files/{id}` with only `name` renames and keeps the bytes, size and type; with a `file` it replaces bytes, size and mime type, checked against the limits again. 200 with the same shape.
- [x] AC5 `GET /files/{id}` returns the metadata and never the bytes. An unknown id, another account's file and a soft-deleted file are the same 403 `FORBIDDEN`, for GET and PATCH.
- [x] AC6 Each change is committed by the route (ADR-0021): a following GET shows it; a failed validation leaves the row as it was.
- [x] AC7 An uploaded file's id is accepted as `avatarId` by `PATCH /accounts/{id}/profile` (end-to-end over HTTP).
- [x] AC8 `openapi.json` is regenerated, the stale test passes, and the response model holds no ORM class and no bytes.

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| PATCH with neither `file` nor `name` | 200, nothing changes, current metadata returned | Node (empty update is a no-op) |
| PATCH `name` only on a row with no content | 200, renamed | ENDPOINTS `updateFile` |
| Empty `file` part (0 bytes) with a filename | allowed by size; type still checked | `assert_upload` accepts 0 |
| 0-byte `file` part with an empty filename | 422, FastAPI treats it as a missing part | framework (gate finding) |
| `file` or `name` sent twice | the last part wins, no error (Starlette keeps the last value) | framework (gate finding); a test pins it for `name` (the same parser handles `file`) |
| Body between `FILE_MAX_SIZE` and `MAX_REQUEST_BODY_BYTES` (12 MiB) | 413 from the service check | 8.1, RUNBOOK |
| Body over 12 MiB | 413 from the middleware before routing | task 1.6 |
| Mime type with parameters (`image/PNG; charset=x`) | accepted as `image/png`; the stored type is the declared one, trimmed to the media type (assumption Q3) | 8.1 `_media_type` |
| Unknown form field | ignored by Starlette multipart (assumption Q4) | framework |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| Q1 | `python-multipart` is not a dependency and FastAPI refuses `UploadFile`/`Form` without it. May it be added to `pyproject.toml` and `uv.lock` (rule C2)? | Yes, it is the library FastAPI documents for this; there is no alternative short of parsing multipart by hand | **answered: yes, approved by Volodymyr · 2026-11-09** |
| Q2 | Name when `name` is omitted | the upload's filename if it passes the `FileName` limits, else `null` (the column is nullable). A new decision, not read from Node: ENDPOINTS.md records it | no |
| Q3 | Stored `mimeType` | the media type without parameters, lowercased | no |
| Q4 | Unknown form fields | ignored, not 422 (multipart cannot use `extra="forbid"` the way JSON models do) | no |
