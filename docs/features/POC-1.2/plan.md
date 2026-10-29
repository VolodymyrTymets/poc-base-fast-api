# POC-1.2 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     Approving confirms the assumed answers in spec.md (edit them first to change one); assumption 5 needs an
     explicit yes. Format: Approved-by: volodymyr · <date> — assumption 5 yes -->
Approved-by: volodymyr · 2026-10-29

Pattern followed: the Node resolvers and `api/schema.gql` in `/Users/work/Documents/projects/poc-base` (read-only) are the
source of behaviour; ADR-0003 (`docs/decisions/ADR-0003-rest-api-fastapi-openapi.md`) is the precedent for shape (`/api/v1`,
the error body and the eight codes), with ADR-0008 and ADR-0009 for tokens and files. Layer: documentation only.

## Contract changes
- boundary: this PR *writes down* the REST contract; no endpoint exists yet. It adds one route Node never had, `GET /api/v1/files/{id}/content` (ADR-0009).
- data: none. generated output: none (`openapi.json` comes in 4.1).

## Requirements (ordered, each independently verifiable, one commit each)

Branch `feat/POC-1.2-endpoint-map`, one draft PR (rule A4), cut from `main` (PR #2 with the ADRs is merged, so the ADR links resolve). All work is in `docs/api/ENDPOINTS.md` (new) unless stated. Layer: docs. Risk: none unless noted.

### R1 — Document skeleton, conventions and mapping decisions (S)
- Exactly five `##` headings, in this order: `Conventions`, `Auth endpoints`, `Account and profile endpoints`, `File endpoints`, `Mapping decisions`. The three endpoint sections each hold one table, first column the GraphQL operation in backticks (the new route's first cell is `(new)`), columns: Operation, Method and path, Request, Response, Success, Errors, Auth, Roles, Node source. No separate coverage table (the Node source column carries it).
- Conventions: base path `/api/v1`; auth schemes (Bearer access token; `x-refresh-token` only on refresh); error body and the eight codes by reference to ADR-0003; shared validation rules (email valid, max 254, trim + lowercase; password 8 to 72 bytes, no control characters; phone valid E.164); status-code rules. Mapping decisions: spec assumptions 1 to 5, the new content route, nullable phone, dropped GraphQL-only features (field selection; `DateTime` becomes an ISO 8601 string).
- test: `grep -c '^## ' ENDPOINTS.md` prints 5, and `grep '^## '` prints the five names above.
- executed how: run both and paste the output.

### R2 — Auth routes: 9 operations (M)
- `signInOtp` `POST /auth/otp/request`; `verifyOtp` `POST /auth/otp/verify`; `signUp` `POST /auth/sign-up` (201); `signIn` `POST /auth/sign-in`; `refreshToken` `POST /auth/refresh`; `signOut` `POST /auth/sign-out`; `changePassword` `POST /auth/password/change`; `restorePassword` `POST /auth/password/restore`; `resetPassword` `POST /auth/password/reset`.
- Behaviours to record (each with its Node source): OTP code in the body only when `APP_ENV` is local, development or test; unknown phone creates a customer; OTP TTL 2 minutes; expired, wrong or unknown all 401 `INVALID_CREDENTIALS`; sign-up duplicate 409 `EMAIL_ALREADY_REGISTERED`; sign-in unknown email, wrong password, OTP-only and deleted accounts all 401 `INVALID_CREDENTIALS`; restore answers `{success: true}` for any well-formed email and never returns the token; reset consumes the token once, bad or expired 400 `INVALID_RESET_TOKEN`, and ends every session; change password verifies the current one and ends every session; sign-out clears the refresh hash.
- test: coverage check 1 of R4 for these nine names, and check 4 (the header only in Conventions and the refresh row).
- executed how: run the check.

### R3 — Account, profile and file routes: 5 operations plus content (M)
- `account` `GET /account`; `updateAccountProfile` `PATCH /accounts/{accountId}/profile`; `createFile` `POST /files` (multipart, 201); `updateFile` `PATCH /files/{id}`; `file` `GET /files/{id}`; `(new)` `GET /files/{id}/content`.
- Behaviours: `GET /account` with a token whose account is gone is 401 `UNAUTHORIZED`; profile needs a valid token and role ADMIN or CUSTOMER, `accountId` must equal the caller (else 403 `FORBIDDEN`), a missing profile is 404 `NOT_FOUND`; email normalised, duplicate 409 `EMAIL_ALREADY_REGISTERED`; field limits (names 50, date of birth 10, SSN 20, email 254); avatar ownership via the file check; files: 10 MB cap (413 `VALIDATION_FAILED`), allowed types jpeg and png (a disallowed or missing mime type is 422 `VALIDATION_FAILED`, assumption 5), owner-only read and update, mime type required with content, unknown and foreign id both 403 `FORBIDDEN`; bytes only through `/content`.
- test: the row checks of R4 for these six rows. executed how: run them.

### R4 — Verification of the whole document and cross-links (S)
- files: `docs/api/ENDPOINTS.md` (final read-through), `docs/ARCHITECTURE.md` (change: the "Boundaries and contracts" line "None yet: no HTTP server, no endpoint, no generated output." becomes "The REST contract is written down in `docs/api/ENDPOINTS.md`; no server, endpoint or generated output exists yet.").
- checks, with expected output (paste the real output into the PR):
  1. the 14 names are read from `schema.gql` with `awk` over the `Query` and `Mutation` blocks; for each, `grep -c -E '^\| `<name>` \|' ENDPOINTS.md` prints 1 (14 lines "name 1"); `grep -c '^| (new) |'` prints 1.
  2. completeness: `awk -F'|' '/^\| (`|\(new\))/{n++; for(i=2;i<=10;i++){gsub(/ /,"",$i); if($i=="")bad++}} END{print n" rows, "bad+0" empty cells"}'` prints `15 rows, 0 empty cells`.
  3. error codes: the backticked tokens in column 7 of those rows, minus the eight codes of ADR-0003, leave nothing: prints `0 unknown codes`.
  4. `grep -n 'x-refresh-token' ENDPOINTS.md` returns exactly two lines: one in Conventions, one in the `POST /auth/refresh` row.
  5. every `docs/decisions/ADR-00NN` file named in the doc exists; `git diff --name-only main` lists only paths under `docs/`.
  6. `uv sync && uv build` unchanged.
  7. ADR agreement checklist, pasted into the PR: each decision bullet of ADR-0008 (sha256 refresh hash cleared on sign-out, password change and reset; `x-refresh-token` only on refresh; access vs refresh secrets), ADR-0009 (multipart; 10 MB cap; jpeg and png; owner-only content; 413) and ADR-0010 (`APP_ENV`; 15 minute access token) paired with the `ENDPOINTS.md` line that honours it.
- Cells containing `|` (for example `string \| null` for the nullable phone) are written with the pipe escaped, or the check 2 count would be wrong; the check output proves it.

## Docs to update in this PR
- [x] docs/features/POC-1.2/spec.md (acceptance criteria ticked)
- [x] docs/ARCHITECTURE.md — replace the "None yet" contracts line with a pointer to the endpoint map
- [x] docs/DOMAIN_GLOSSARY.md — none expected
- [x] docs/decisions — none in this PR. Assumption 5 (413 and 422 carry `VALIDATION_FAILED`) is recorded in the doc's "Mapping decisions" and handed to task 4.2 (`docs/api/ERRORS.md`, ADR-0003's own follow-up) as an input; if you say no, R3 and "Mapping decisions" change before any commit

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| A Node behaviour is missed because only the resolvers were read | later tasks diverge silently | read the service layer for each op (`jwt-auth-strategy`, `otp-auth-strategy`, `file-assert`, `account-profile`) and cite file and line per behaviour; the PR review is the second check |
| Mapping a Node error to a REST status changes meaning (401 carrying `NOT_FOUND`) | clients mis-handle it | assumptions 1 to 3 are stated in the spec and listed in "Mapping decisions" for the reviewer |
| An ADR link breaks | broken reference | the R4 check opens every referenced ADR file |
| `Account.phoneNumber` nullability (issue I.3) is easy to forget | wrong model in 5.3 | stated in the account row |

## Assumptions
- Spec assumptions 1 to 5 hold; the `Approved-by:` line confirms them, and assumption 5 needs an explicit yes (a client-visible contract). Estimates: R1 S, R2 M, R3 M, R4 S (about 3 h in total, as in the scope doc).
- PR #2 is merged. The Node repo is read-only.
- Ticket `POC-1.2`; the human reviewer is the backend owner (volodymyr).
