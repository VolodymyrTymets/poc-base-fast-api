# POC-6.3 — NotifierService fan-out

## Problem
The jobs of 6.2 exist but nothing hands work to them. The auth flows (7.1 OTP request, 7.6 password restore) need one service that, given an account and a list of
channels, queues the right job on each, and that never lets a delivery failure change the answer a client sees (a throw would reveal which emails exist).

## Goal / business value
Goal 2 (authentication): 7.1 and 7.6 start on a tested notifier. Goal 1: a fork adds a channel by adding one method and one job.

## Scope
- in: `NotifierType` (`SMS`, `LOG`, `EMAIL`, `ALL`) and `NotifierService` in `app/services/notifier.py`; `get_notifier_service` in `app/dependencies.py` (ADR-0025);
  tests on the real database with `FakeQueue`.
- API: `notify_about_totp_code(account_id, code, types)` and `notify_about_password_reset(account_id, token, types)`. Each reads the account's live profile
  through `AccountProfileService.get_by_account_id`, then per selected channel:
  - SMS channel, OTP: profile has a phone number → `queue.enqueue("send_totp_code", phone, code)`; none → nothing. SMS channel, reset: nothing.
  - EMAIL channel, reset: profile has an email → `queue.enqueue("send_password_reset", account_id, email, token)`; none → nothing. EMAIL channel, OTP: nothing.
  - LOG channel: logs that a notification was issued for the account id, never the code or token (Q1). `ALL` selects the three channels.
- A `QueueUnavailableError` (new, `app/core/queue.py`: Redis down or unreachable) from a channel's enqueue is logged with the account id and the exception, not raised; the other channels still run. A database error while reading the profile is not caught: it is not an enumeration signal, and swallowing it would leave the caller's transaction aborted unnoticed.
- **out (explicit):** any route or caller (7.1, 7.6), rate limiting, a real provider, job retention or retry settings (arq in 6.1), delivery receipts, new jobs, new dependencies, `openapi.json` changes.

## Acceptance criteria
- [x] AC1 Given an account with phone and email, `SMS` + OTP enqueues exactly `send_totp_code(phone, code)`; `EMAIL` + reset enqueues exactly `send_password_reset(account_id, email, token)`; `ALL` does both for the matching message kind and nothing else.
- [x] AC2 An account with no phone gets no SMS job; with no email gets no email job; a missing, soft-deleted or unknown account gets none and no error.
- [x] AC3 `SMS` on a reset and `EMAIL` on an OTP enqueue nothing (Node spec case 3).
- [x] AC4 When the queue raises `QueueUnavailableError` for one channel, both methods return normally, the failure is logged with the account id, and the other selected channels still run.
- [x] AC5 No log line from the service holds the code, the token, the email or the phone (rules D8, P4); checked on the formatted JSON.
- [x] AC6 An empty `types` list enqueues nothing.
- [x] AC7 `get_notifier_service` gives the request's `AccountProfileService` and `get_queue`; a test can swap it with `dependency_overrides`; `openapi.json` unchanged; no new dependency.

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| Same channel listed twice (`[SMS, SMS]`, `[SMS, ALL]`) | one job per channel, not two | assumption A2 |
| Queue raises `QueueUnavailableError` for one channel; any other error from the queue | the first: logged, the next channel runs; the second propagates (a bug, rule D5) |
| Profile read fails (database error) | propagates to the caller (analyze advisory 1) | assumption A3 |
| Profile phone is `None` (password account, I.3) | no SMS job | Node parity |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| Q1 | Node's `LogNotifierService` writes the OTP code to the log at debug level in `local`. Rules D8 and P4 forbid it, and ADR-0026 covers only the reset token. | Do not port it: the LOG channel logs `notification issued for account <id>` with no code. In local/development/test, 7.1 returns the code in the response body anyway, so nothing is lost. | yes, at approval (security, rule F2): write the answer here when approving; a different one needs an ADR like 0026. Answer: accepted as proposed (Volodymyr, 2026-11-04) |
| Q2 | `ALL` | all three channels | no |
| Q3 | Identify the account by id, not by an `Account` object | `account_id: str`; the service loads the live profile itself, so a stale object cannot send to an old number | no |
| Q4 | Retries and job retention (Node: attempts 3, backoff, removeOnComplete) | arq already does it for every job (`max_tries=3`, `keep_result=0`, 6.1) | no |
| Q5 | Does the service depend on `AccountProfileService` or query the model itself | on `AccountProfileService` (reuse, D1; a provider that needs a service depends on its provider, ADR-0025) | no |
