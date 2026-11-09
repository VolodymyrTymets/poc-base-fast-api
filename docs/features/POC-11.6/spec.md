# POC-11.6 — Hardening

## Problem
The API serves its Swagger UI, ReDoc and `openapi.json` in every environment, sends no security headers, and its logs cannot be tied to one request. The scope doc's issue list has no recorded status, so nobody can tell which of the ten known issues are closed.

## Goal / business value
Goal 2 (authentication a new POC can rely on as-is) and goal 1 (a fork starts from a safe default): a fork that sets `APP_ENV=production` does not expose its contract pages, and an incident can be followed through the logs by one request id.

## Scope
- in:
  - `/docs`, `/redoc` and `/openapi.json` served only for `APP_ENV` `local` and `development` (the scope row says "off outside local/development");
  - security response headers on every response the app itself sends;
  - a request id: accepted from `X-Request-ID` when well-formed, otherwise generated; echoed in the response header; present on every JSON log line written while the request is handled;
  - a status, with its evidence, for each issue I.1 to I.10;
  - ADR-0033, RUNBOOK, ARCHITECTURE, `docs/api/ENDPOINTS.md` (the header convention) and DOMAIN_GLOSSARY (request id).
- **out (explicit):** rate limiting, email verification, re-authentication on email change, httpOnly-cookie refresh tokens (issue I.8 stays open, out of scope for the whole base); HSTS and a Content-Security-Policy (see edge cases); a request id inside worker jobs; a request-id tag on Sentry events; changing the exported `openapi.json`; a new setting.

## Acceptance criteria
- [x] AC1 Given `APP_ENV=production` or `test`, when `GET /docs`, `/redoc` or `/openapi.json` is called, then each answers 404 with the error body; given `local` or `development`, each answers 200.
- [x] AC2 `uv run python -m app.cli --export-openapi` still writes the same `openapi.json` (the export does not depend on the served route), and `--check` exits 0.
- [x] AC3 Every response the app sends, including 404, 413 and 422, carries `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` and `Cache-Control: no-store`; a response that already sets one of them keeps its own value.
- [x] AC4 Given no `X-Request-ID`, the response carries a generated one; given a well-formed one (1 to 64 characters of `A-Z a-z 0-9 . _ -`), the response echoes it; given a malformed one, it is replaced by a generated one and the bad value is not logged.
- [x] AC5 Every JSON log line written during a request has a `request_id` equal to the response header, including lines logged by services and by uvicorn's access log; a line outside a request has none.
- [x] AC6 Two concurrent requests log their own ids (no leak between requests).
- [x] AC7 No new setting, dependency or `openapi.json` change; `uv.lock` untouched.
- [x] AC8 `docs` states a status and the evidence for each of I.1 to I.10; every status was checked against the code or a command, not copied.

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| An unhandled exception (500) | measured: no security headers (Starlette's outermost handler sits outside our middleware, the same limitation as CORS, ERRORS.md); the request id is added by the handler itself, in the header and in the `unhandled error` log line, because the var is reset by then | assumption A2, extended in R3 |
| `X-Request-ID` is 10 000 characters, or has a newline or a space | replaced by a generated id; never echoed or logged | AC4 |
| A response already sets `Cache-Control` (a later file route) | its own value is kept | AC3 |
| The Swagger UI page under the headers | `X-Frame-Options: DENY` and `no-referrer` do not break it; no CSP is sent, because the UI loads its script from a CDN and inline | assumption A3 |
| HSTS | not sent: the app is plain HTTP behind whatever terminates TLS, and a browser ignores the header on HTTP; the proxy sets it | assumption A3 |
| `APP_ENV=test` | docs off (the row names only local and development) | assumption A1 |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| A1 | Which environments serve the docs | `local` and `development` only, derived from `APP_ENV`, no new setting; `test` is off | confirm |
| A2 | 500 responses and the middleware | document the limitation, do not restructure the middleware stack | no |
| A3 | Header set | the four in AC3; no HSTS, no CSP | confirm |
| A4 | Where the issue statuses live | a table in `docs/ARCHITECTURE.md` "Known constraints and landmines", with the evidence; the scope doc (outside the repo) is left to its owner | confirm |
| A5 | Request id name and format | `X-Request-ID`, the common name; a uuid4 hex when generated | no |
