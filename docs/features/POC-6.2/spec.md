# POC-6.2 — send_totp_code and send_password_reset jobs

## Problem
The worker (6.1) runs only a `ping` smoke job. The auth flows (7.1 OTP request, 7.6 password restore) and the notifier (6.3) need two real jobs to hand a message to,
and the Node base's SMS job logs the full phone number (issue I.5, rule D8).

## Goal / business value
Goal 2 (authentication: a new POC can finish the OTP and reset flows by reading the worker log) and goal 1 (log-only senders a fork replaces with a provider).

## Scope
- in: `send_totp_code` in `app/workers/sms.py`, `send_password_reset` in `app/workers/email.py`, both registered in `WorkerSettings.functions`; ADR-0026 for the logging exception;
  unit tests porting `email-sender` (3 cases) and `sms-sender` (the Node spec only checks "is defined", so the real assertions are new: masked phone, code never logged); one real-Redis e2e test.
- **out (explicit):** `NotifierService` and anything that enqueues (6.3, 7.x), a real SMS or email provider, a job for any other message, `ping` removal, new settings, new dependencies, `openapi.json` changes.

## Job contracts (JSON arguments, ADR-0005)
- `send_totp_code(ctx, phone: str, code: str)`. Logs `[SMS] TOTP code sent to <masked phone>` in every environment. The code is never logged.
- `send_password_reset(ctx, account_id: str, email: str, token: str)`. In `local`, `development`, `test`: `[EMAIL] Password reset for <email> (account <id>): token <token>`.
  Elsewhere: `[EMAIL] Password reset email queued for account <id>; no email provider is configured` (no email, no token).
- Both are idempotent: no state, no external call, a retry only logs the same line again. Neither raises, so no `Retry`.

## Acceptance criteria
- [x] AC1 Given Redis, a worker with `APP_ENV=local` and `send_password_reset` enqueued through `ArqQueueClient`, then the worker log has `[EMAIL] Password reset … token …` with the real email and token.
- [x] AC2 With `APP_ENV=production` the same job logs the account id only: neither the email nor the token appears anywhere in the output.
- [x] AC3 `send_totp_code` logs the phone masked (I.5): at most its last 4 digits, never the full number, in every environment; the OTP code appears in no log line.
- [x] AC4 Calling either job twice with the same arguments gives the same log line twice and no error.
- [x] AC5 Both functions are in `WorkerSettings.functions` beside `ping`; arguments still never reach arq's own log lines (`HideJobArguments`, AC8 of 6.1).
- [x] AC6 `openapi.json` unchanged; no new dependency.

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| Phone shorter than 5 digits or not a number | fully masked, nothing raised | assumption A2 |
| Unknown `APP_ENV` value | cannot happen: `Settings.app_env` is a closed Literal | config |
| Job name not handled | arq's "function not found" (6.1 edge case) | arq |
| Email with a `+` tag or non-ASCII | logged as given in local/dev/test | Node parity |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| Q1 | Logging the reset token in clear in local/development/test | Yes, as an explicit exception to D8/P4 (ADR-0026, with a `WHY` comment on the log call), as the Node base and the acceptance criterion require. The redaction filter does not catch `token <value>` (no `=` or `:` after the key), so the line survives it; a unit test pins that. A `development` host shared with others will show the token in its logs. | decided 2026-11-04 by Volodymyr: keep it, recorded in ADR-0026 |
| Q2 | Mask format | `***` plus the last 4 digits (`***0100`); fewer than 5 digits: `***` | no |
| Q3 | Where the job reads `APP_ENV` | from `get_settings()` (cached); a test sets the env and clears the cache | no |
| Q4 | Job arguments: Node used a dict, arq uses positional JSON | positional arguments, named as above | no |
