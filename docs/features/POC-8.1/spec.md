# POC-8.1 — FileAssertService

## Problem
Nothing checks an upload or a file's owner. Task 8.2/8.3 (file routes) and task 5.4 (profile avatar: "an `avatarId` must be a file the caller owns")
all need the same checks, and 5.4 depends on 8.1 (scope doc). The Node base has them in `FileAssertService`
(`files/services/file-assert.service.ts`).

## Goal / business value
Goal 2 (a reusable, understandable pipeline) and goal 1 (one place for file rules a fork changes through settings). Unblocks 5.4, 8.2, 8.3.

## Scope
- in: the settings `FILE_MAX_SIZE` and `FILE_ALLOWED_MIME_TYPES` (`app/config.py`, already in `.env.example`); a 413 error class in `app/core/errors.py`;
  `FileAssertService` in `app/services/file_assert.py`: `assert_upload(size, mime_type)` (size and type of a new or replacing upload) and
  `get_owned_file(file_id, account_id)` (the owner check for read, update and avatar use).
- **out (explicit):** the routes, multipart parsing, creating or storing a file (8.2), streaming (8.3), the avatar update (5.4), virus or magic-byte sniffing
  (the mime type is the one the client declares, as in Node), a new error code (ADR-0003).

## Acceptance criteria
- [ ] AC1 Given a size over `FILE_MAX_SIZE`, `assert_upload` raises a 413 `VALIDATION_FAILED` whose `details` name the field `file`; a size equal to the limit passes.
- [ ] AC2 Given a mime type outside `FILE_ALLOWED_MIME_TYPES`, or none, it raises a 422 `VALIDATION_FAILED` naming `file`; the comparison ignores case and any `; parameters`.
- [ ] AC3 `get_owned_file` returns the file (metadata, not the bytes) when the account created it.
- [ ] AC4 An unknown id, another account's file and a soft-deleted file all raise `ForbiddenError` (403), so a file's existence is not leaked (ENDPOINTS decision 3, rule P6).
- [ ] AC5 `Settings` reads `FILE_MAX_SIZE` (default 10485760, must be above zero) and `FILE_ALLOWED_MIME_TYPES` (comma-separated, default jpeg and png; blank entries dropped; an empty list is refused at boot).
- [ ] AC6 Error text and `details` never hold the file name, bytes or the submitted mime string (rules D8, P4); they name the limit and the field only.
- [ ] AC7 `openapi.json` is unchanged (`--export-openapi --check`).

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| Node's `deleted` filter | Node did not filter soft-deleted files (`count` on id and creator); here a soft-deleted file is 403: a stated difference, rule P6 | AC4 |
| Replacing content without a mime type | Node fell back to the stored `mimeType`; here the upload always carries its own type (ENDPOINTS decision 10), so a missing type is 422 and there is no fallback | AC2 |
| Size 0 | passes the size check; "a file is required" is the router's 422 (8.2) | assumption Q2 |
| `image/PNG`, `image/png; charset=x` | accepted as `image/png` | AC2 |
| File exists but is owned by an admin, caller is an admin of another account | still 403: ownership is by creator only | ENDPOINTS "Ownership" |
| Session has the file already loaded with bytes | returned as is; the query itself never selects `content` | AC3 |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| Q1 | Which exception for 413? | `PayloadTooLargeError(ValidationFailedError)` with status 413, same code `VALIDATION_FAILED` (ERRORS.md already says an oversized upload is 413) | no |
| Q2 | Is an empty upload valid at this layer? | Yes; the router rejects a missing file | no |
| Q3 | The Node `file-assert.service.spec.ts` cases | Ported where they still apply; the mapping of all 8 is the table in plan.md (the Node repo is at `/Users/work/Documents/projects/poc-base`, read-only) | no |
