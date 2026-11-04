# ADR-0026 — The password-reset job logs the email and token in local, development and test

- **Date:** 2026-11-04
- **Status:** accepted
- **Deciders:** volodymyr
- **Ticket:** POC-6.2
- **Supersedes:** nothing. It is a recorded exception to rules D8 and P4 of `CLAUDE.md` and to the "no tokens in logs" non-negotiable of `docs/BUSINESS_MODEL.md`, for one job.

## Context
No email provider is wired (out of scope, `docs/BUSINESS_MODEL.md`), so "sending" a password-reset message is logging it. Scope doc row 6.2 and the Node base both
write the recipient and the reset token to the worker log where a developer needs them to finish the flow by hand. Rules D8 and P4 forbid tokens in logs. The plan gate
blocked POC-6.2 on that conflict and the decision below was taken by a human (rule F2).

## Decision
- `send_password_reset` (`app/workers/email.py`) logs the recipient email and the reset token in clear only when `APP_ENV` is `local`, `development` or `test`:
  `[EMAIL] Password reset for <email> (account <id>): token <token>`. The log call carries `# WHY: ADR-0026, POC-6.2`.
- In every other environment (`production`) it logs the account id only: no email, no token.
- `send_totp_code` (`app/workers/sms.py`) is not part of the exception: it logs the phone masked (last four digits) in every environment and never logs the OTP code.
- No other job, route or service may log a token, a password or an OTP code on the strength of this ADR.

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| Never log the token or the email | the scope doc's acceptance criterion (`[EMAIL] Password reset … token …` locally) and the manual reset flow in the runbook need it |
| `local` and `test` only | a shared `development` host would then be unusable for the reset flow without a provider; accepted risk below instead |

## Consequences
- Anyone with read access to the logs of a `development` host sees live reset tokens. `development` must not hold real accounts.
- The line format is deliberate: `redact` (`app/core/logging.py`) replaces `token=<v>` and `token: <v>`, but not `token <v>`, so the line survives the formatter.
  That is a dependency on a gap in best-effort redaction: `tests/unit/test_worker_email.py` fails if `redact` ever starts matching it, and the owner then decides
  again instead of the exception disappearing silently.
- A fork that adds a real provider deletes the log branch and keeps the production line.
