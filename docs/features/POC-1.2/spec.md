# POC-1.2 — Endpoint map: every GraphQL operation as a REST route

## Problem
The Node base exposes 14 GraphQL operations (`Query`: `account`, `file`; `Mutation`: `updateAccountProfile`, `createFile`,
`updateFile`, `signInOtp`, `verifyOtp`, `signUp`, `signIn`, `refreshToken`, `restorePassword`, `resetPassword`,
`changePassword`, `signOut`). ADR-0003 decided REST, but nothing says which route, body, status code, auth and role each
operation becomes, or which Node behaviours must survive. Tasks 4.x to 8.x all build from that mapping.

## Goal / business value
Goal 2 (authentication) and goal 1 (scaffolding): a port that keeps the Node behaviour is only checkable against a written
list of what the behaviour is. This is the reference the scope doc names for packages 4 to 8.

## Scope
- in: `docs/api/ENDPOINTS.md` with, per operation, method, path, request and response model, status codes, auth, roles,
  the error codes it can return, the Node source it was read from, and the behaviours it must keep. A conventions section
  (base path, auth schemes, error body, shared validation rules, status-code rules). A list of mapping decisions the doc makes.
- **out (explicit):** any code, Pydantic model or `openapi.json` (4.1); the ERRORS.md catalogue (4.2); validation code (4.3);
  new endpoints beyond the Node base (except the `GET /files/{id}/content` that ADR-0009 already decided); editing the Node repo
  or the ADRs; rate limiting and the other open items of Node ADR-0011.

## Acceptance criteria
- [ ] AC1 Given `api/schema.gql` in the Node repo, when I list its `Query` and `Mutation` fields, then each of the 14 appears in exactly one row of `ENDPOINTS.md`.
- [ ] AC2 Each row gives method, path (under `/api/v1`), request fields with types and limits, response fields, success status, error codes, auth, roles, and the Node source file.
- [ ] AC3 Every error code in the doc is one of the eight defined by ADR-0003, and every auth, token and file rule agrees with ADR-0008, ADR-0009 and ADR-0010.
- [ ] AC4 The behaviours named in the scope doc are recorded where they apply: OTP code in the response only in local, development and test; `restorePassword` always succeeds and never returns the token; password 8 to 72 bytes and no control characters; email trimmed and lowercased; sign-in failures indistinguishable; ownership checks on profile and files.
- [ ] AC5 Differences from Node (status codes, `NOT_FOUND`, the new content route, nullable phone number, GraphQL-only fields dropped) are listed in one "Mapping decisions" section, each with a reason.
- [ ] AC6 `docs/ARCHITECTURE.md` links the doc; the PR body carries the coverage-check output.
- [ ] AC7 The diff touches only `docs/`; `uv sync` and `uv build` still pass.

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| Node returns HTTP 200 with a GraphQL error for every failure | each failure gets a real status code from ADR-0003 | ADR-0003 |
| Node throws `Unauthorized` carrying `NOT_FOUND` or `FORBIDDEN` | REST uses 404 and 403 with the matching code | this plan, see assumption 1 |
| File that does not exist vs one owned by someone else | both 403 `FORBIDDEN`, as in Node, so existence is not leaked | this plan, assumption 2 |
| Upload over the size cap, or a disallowed or missing mime type | 413 or 422 with `VALIDATION_FAILED` (assumption 5); Node's 403 is not kept for these | this plan, assumption 5 |
| OTP expired, wrong code or unknown account | 401 `INVALID_CREDENTIALS` (never `UNAUTHORIZED`, which triggers a client refresh) | this plan, assumption 3 |
| `Account.phoneNumber` is non-null in GraphQL but absent for password accounts | nullable in the REST model (scope-doc issue I.3) | scope doc |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| 1 | Unknown profile or account for a valid token: keep Node's 401, or 404? | `GET /account` missing account: 401 `UNAUTHORIZED` (the token no longer maps to an account). `PATCH` profile missing: 404 `NOT_FOUND` | confirm |
| 2 | Unknown file id: 404 or 403? | 403 `FORBIDDEN` for both, as Node | confirm |
| 3 | Error code for a bad or expired OTP? | `INVALID_CREDENTIALS` 401, no new code | confirm |
| 4 | Which success status for creating things (`sign-up`, `files`)? | 201 for `sign-up` and `POST /files`, 200 for the rest | no |
| 5 | ADR-0003 has eight error codes and none for upload failures. Node returns 403 for an oversized file, a disallowed mime type and content sent without a mime type; ADR-0009 says an oversized upload is 413. What do the three become? | oversized: 413 with code `VALIDATION_FAILED`; disallowed or missing mime type: 422 with `VALIDATION_FAILED` and per-field `details`. No new code, so ADR-0003 is not reopened | answered: yes (volodymyr, in chat, 2026-10-29) |
