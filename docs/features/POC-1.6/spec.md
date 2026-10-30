# POC-1.6 — Logging with redaction, Sentry, body limit, graceful shutdown

Scope-doc row 1.6 (3 h). Depends on 1.1 and 1.4/1.5 (both merged). The ticket text: "JSON logging with a redaction filter (no tokens,
passwords, SSN, DOB, phone), Sentry off for `local` or no DSN, request body limit, graceful SIGTERM". Acceptance in the doc:
"Oversized body → 413; a log line with a token is redacted".

## Problem
The server logs in uvicorn's plain format with no guard against sensitive values, and nothing bounds a request body or reports
errors. Rule P4/D8 (no tokens, passwords, SSN, DOB, phone numbers in logs) has no mechanism behind it, and every later task
(auth 7.x, files 8.x) will log through whatever exists now.

## Goal / business value
Goal 1 (scaffolding): a fork inherits a logging setup it does not have to rebuild. Non-negotiable 1 (nothing sensitive in logs)
gets a mechanism instead of a convention. Goal 2 (auth) depends on it being in place before tokens exist.

## Scope
- in: `app/core/logging.py` (JSON formatter, redaction filter, `configure_logging`); Sentry init gated on env and DSN; a pure-ASGI
  body-size limit middleware; uvicorn graceful shutdown wired in `run()`; new settings `LOG_LEVEL`, `SENTRY_DSN`,
  `MAX_REQUEST_BODY_BYTES`, `SHUTDOWN_TIMEOUT_SECONDS`; env templates; one new runtime dependency, `sentry-sdk` (rule C2), and ADR-0013.
- **out (explicit):** request-id in logs and security headers (11.6); the `{"error": {...}}` handlers (4.2); upload size/mime
  checks (8.x, `FILE_MAX_SIZE`); log shipping; Sentry performance tracing; arq worker logging (6.1 reuses `configure_logging`);
  rate limiting (P3).

## Acceptance criteria
- [ ] AC1 Given any log record, when it is formatted, then the output is one JSON object per line with `timestamp`, `level`, `logger`, `message`.
- [ ] AC2 Given a record whose message, args or `extra` fields carry a JWT, a `Bearer` header value, a password, SSN, DOB or phone number, then each value is replaced by `[REDACTED]` in the output; non-sensitive text is untouched.
- [ ] AC3 Given `APP_ENV=local`, or an unset/blank `SENTRY_DSN`, then `sentry_sdk` is not initialised; given another env and a DSN, it is, with `send_default_pii=False`, no local variables, and every string and every sensitive key anywhere in events and breadcrumbs (body, headers, query, contexts, breadcrumb data) redacted by the same filter as AC2; request bodies and local variables are not sent.
- [ ] AC4 Given a request whose body exceeds `MAX_REQUEST_BODY_BYTES`, declared by `Content-Length` or counted while streaming, then the response is 413 and the route handler never sees the body.
- [ ] AC5 Given a body at exactly the limit, then it is accepted.
- [ ] AC6 Given the running server receives SIGTERM, then it stops accepting connections, finishes in-flight requests within `SHUTDOWN_TIMEOUT_SECONDS`, runs the lifespan shutdown (logged), and ends with the SIGTERM status (-15, shown as 143 by a shell or container). *Corrected in R4: the plan said "exits 0", but uvicorn re-raises the captured signal after a graceful shutdown (`uvicorn/server.py:348`), so 0 is not what it does.*
- [ ] AC7 Given a bad `LOG_LEVEL` or a non-positive limit, boot fails naming the field.
- [ ] AC8 Docs match: ARCHITECTURE, RUNBOOK, ENDPOINTS (413 row), env templates.

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| Exception log with a traceback containing a token | the formatted traceback goes through the same redaction | R1 test |
| Chunked body with no `Content-Length` | counted while streaming; 413 once the limit is crossed | R3 test |
| `Content-Length` lies (smaller than the real body) | the streaming count still stops it | R3 test |
| Redaction of a key by name (`password=...`, `"ssn": "..."`) and of a value by shape (JWT) | both | R1 test |
| `SENTRY_DSN` set but malformed | boot fails at `sentry_sdk.init`, not silently ignored (rule D5) | R2 test |
| 413 for a browser request | carries CORS headers (body limit sits inside CORS) | R3 test |
| Server killed with SIGKILL | out of scope, nothing to handle | — |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| 1 | May `sentry-sdk` be added (C2), knowing it sends runtime errors (message, stack, breadcrumbs) to an outside service (F2)? | Yes, for non-`local` envs with a DSN only, after our redaction hooks run and with `send_default_pii=False`, no local variables. ADR-0013 records it. The `Approved-by:` line confirms it. | yes |
| 2 | Default body limit? | 12 MiB (12582912): `FILE_MAX_SIZE` is 10 MB and multipart adds overhead; 8.x enforces the real file limit. | no |
| 3 | 413 body shape before 4.2 exists? | `{"error": {"code": "VALIDATION_FAILED", "message": "Request body too large", "details": []}}` written by the middleware, matching ENDPOINTS.md; 4.2 may later route it through its handler. | no |
| 4 | Redaction approach? | Key-name match (`password`, `token`, `authorization`, `secret`, `ssn`, `dob`, `date_of_birth`, `phone`) on `extra`/dict args, plus regex on message text for JWT shape, `Bearer ...`, SSN `ddd-dd-dddd`, and `key=value` pairs for those names. Best effort, not a guarantee; callers still must not log secrets (P4). | no |
| 5 | Hand-written JSON formatter or a library? | Hand-written on stdlib `logging` (about 30 lines); avoids a second new dependency (C2). | no |
