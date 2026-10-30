# ADR-0013 — Sentry error reporting with whole-event redaction

- **Date:** 2026-10-30
- **Status:** accepted
- **Deciders:** volodymyr
- **Ticket:** POC-1.6

## Context
Scope-doc row 1.6 asks for Sentry that is off for `local` and when no DSN is set. Sentry is an outside service: whatever it
receives leaves the process. Its default integrations read log records, requests and stack frames on their own, outside our
log formatter, so redacting log lines alone (rule P4) would leave a second path to the same sensitive values.

## Decision
- `sentry-sdk` is a runtime dependency. `init_sentry(settings)` (`app/core/sentry.py`) starts it only when `APP_ENV` is not
  `local` and `SENTRY_DSN` is non-blank. A malformed DSN stops the boot (rule D5).
- `data_collection` turns every automatic channel off: user info, cookies, request headers, request bodies, query strings and
  stack-frame variables. It replaces `send_default_pii`, `include_local_variables` and `max_request_body_size`, which the SDK
  deprecates in favour of it.
- `before_send` and `before_breadcrumb` walk the whole event or breadcrumb and apply the log redaction (`redact_mapping`): a
  sensitive key hides its whole value, and every string is scanned for tokens, SSN, phone numbers and `key=value` pairs. If the
  redacted result is not a dict the event is dropped.
- What still leaves the process: the exception type, its redacted message, the stack trace without variable values, the
  environment name, the SDK and runtime versions, and breadcrumbs from log records (redacted).
- No performance tracing and no Sentry logs product: `traces_sample_rate` and `enable_logs` stay at their defaults (off).

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| Rely on `send_default_pii=False` and Sentry's own scrubber | it matches key names only, so a token inside a message string, and ssn, dob or phone values, would be sent |
| Disable the logging integration | it is also how errors logged with `logger.exception` reach Sentry; the hooks make it safe instead |
| Do not add Sentry | the scope doc asks for it; the gate makes it optional per environment |

## Consequences
- Positive: one redaction implementation serves log lines and Sentry; a fork with no DSN sends nothing.
- Accepted cost: redaction is best effort, like the log filter; a fork that logs a secret in an unrecognised shape can still
  leak it. A new sensitive key name is added to `app/core/logging.py` and covers both paths.
- A 413 for an oversized body (task 1.6, R3) uses the same `{"error": {...}}` shape as ADR-0003 with an empty `details`, so task
  4.2 does not read it as a contract break.
- Follow-ups: task 4.2 (error handlers) may route unhandled errors through the same logger; 11.6 reviews the hardening.

## Revisit when
A fork wants performance tracing, release tracking or user context: each is a new decision about what leaves the process.
