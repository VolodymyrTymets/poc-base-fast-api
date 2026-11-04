# POC-6.3 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     Approved-by: -->
Approved-by: Volodymyr · 2026-11-04 — Q1, Q6, Q7 accepted as proposed in the plan and spec

Pattern followed: `app/services/account_profile.py` (a class over collaborators, flushes/never commits, ADR-0021) and its provider `get_account_profile_service` in `app/dependencies.py`
(a provider that depends on another service's provider, ADR-0025); `app/core/queue.py` `QueueClient` and `tests/utils/queue.py` `FakeQueue` for the seam; behaviour from the Node
`api/src/notifier/*` (`notifier.service.ts` fan-out and catch, `sms-notifier`, `email-notifier`). Job names and argument order come from 6.2 (`app/workers/sms.py`, `email.py`).

## Contract changes
- boundary: none (no route); `openapi.json` unchanged.
- `app/core/queue.py`: `ArqQueueClient.enqueue` now raises `QueueUnavailableError` (chained) where it raised arq/Redis errors; no caller catches the old types today (grep in R1).
- internal API 7.1 and 7.6 will call: `NotifierType`, `notify_about_totp_code(account_id, code, types)`, `notify_about_password_reset(account_id, token, types)`, provider `get_notifier_service`.
- job payloads: unchanged from 6.2 (positional JSON).
- config / dependencies: none.

## Requirements (ordered; branch `feat/POC-6.3-notifier-service`, one draft PR, one commit each)

### R1 — QueueUnavailableError and NotifierService (M)
- files: `app/core/queue.py` (change: `class QueueUnavailableError(RuntimeError)` (ADR-0021: a server fault is a `RuntimeError` subclass named for the case); `ArqQueueClient.enqueue` wraps the pool open and `enqueue_job` and raises it `from` the original error, only for `redis.exceptions.ConnectionError`, `redis.exceptions.TimeoutError` and `OSError` (the built-in `TimeoutError` is an `OSError`, which covers arq's `create_pool` timeout); every other `RedisError` (`ResponseError`, `DataError`, ...) propagates unchanged, so a bad ACL or a full Redis is never mistaken for "down"; the `redis.exceptions` import lives there only, see Q6), `tests/utils/queue.py` (change: `FakeQueue(fail_on=...)` raises `QueueUnavailableError`), `docs/decisions/ADR-0027-service-built-from-services.md` (new: extends ADR-0021: a service may be built from other services and core seams such as `QueueClient` instead of a session; the commit rules do not change; first user `NotifierService`), `app/services/notifier.py` (change: docstring-only today). `NotifierType(StrEnum)`; `NotifierService(profiles: AccountProfileService, queue: QueueClient)`; two public methods; private `_send_sms_otp`, `_send_email_reset`, `_log` per channel;
  channels resolved from a set (`ALL` expands to all three, duplicates collapse); the profile is read once, outside any catch: a database error propagates (analyze advisory 1: it says nothing about whether an email exists, and swallowing it would leave the caller's Postgres transaction aborted without telling it). Only each channel's `enqueue` is wrapped: a failure is logged (`logger.exception`, account id only, never code/token/email/phone as arguments) and the next channel runs. Any other error from the queue (`ValueError`, `TypeError`, a plain `RuntimeError`) is a programming error and propagates (rule D5).
- layer: services (imports `core.queue`, `services.account_profile`; no framework object, ADR-0011 rule 6).
- test: `tests/e2e/test_db_notifier_service.py` only (real Postgres through `db_session`, the real `AccountProfileService`; no unit twin, one level per behaviour): accounts are built in the test with the models (`Account` plus `AccountProfile`, as `test_db_account_role_service.py` does); `AccountService` is not changed (C1); AC1 per type and `ALL`; AC2 no phone / no email / soft-deleted profile / unknown account; AC3 cross-kind channels; AC6 empty list; duplicates give one job; AC4 with a queue that raises `QueueUnavailableError` for one job name: both methods return, the other channel's job is still enqueued, an `ERROR` record carries the account id; a queue raising `RuntimeError` makes the call raise (other errors propagate); AC5 on the records of those runs, including the traceback text of the chained error (`JsonFormatter` writes `exc_info`), formatted with `JsonFormatter` (no code, token, email or phone).
  `FakeQueue(fail_on=...)` raises `QueueUnavailableError` for the listed job names, recording nothing; one fake queue, not two. `tests/unit/test_fake_queue.py` (change): `fail_on` raises `QueueUnavailableError` and records nothing. `tests/unit/test_queue.py` (change): a failing pool factory and a failing `enqueue_job` (connection error) each raise `QueueUnavailableError` with the original error as `__cause__` (still exactly one attempt); a `ResponseError` from `enqueue_job` is not wrapped, and the `_`-kwarg `ValueError` is unchanged; the e2e test `test_the_api_boots_without_redis_and_an_enqueue_then_fails` in `tests/e2e/test_worker_arq.py` expects the new type. Both assertions get stricter, not weaker (rule B3).
- executed how: see R3.
- risk: none open; the transaction question is decided above.

### R2 — provider (S)
- files: `app/dependencies.py` (change: `get_notifier_service(profiles=Depends(get_account_profile_service), queue=Depends(get_queue))`; module docstring task list), `tests/e2e/test_http_service_providers.py` (change: the notifier provider cases, mirroring the existing ones: shares the request's profile service, replaced by `dependency_overrides`).
- layer: dependencies. `routers/notifier.py` stays empty.
- test: the provider cases above; `tests/unit/test_routers_use_service_providers.py` keeps passing (no router builds a service).
- executed how: R3.

### R3 — execute for real (S, no code)
- Fiction-range values only (`+1212555xxxx`, `@example.com`, like the 5.5 seeds). Throwaway containers, no volume (the untracked `dump.rdb` is not touched): PostGIS and `redis:7-alpine`; `alembic upgrade head` and seeds on a database of its own; a scratchpad script builds the real objects (`ArqQueueClient`, `AccountProfileService`, `NotifierService`), looks up the seeded sample admin (phone `+12125550100`, email `admin+d1@example.com`, created by the `APP_ENV=local` seeds) with `AccountService.get_by_phone`, calls both methods with `[ALL]`; the worker (`APP_ENV=local`) log shows `[SMS] … ***NNNN` and `[EMAIL] Password reset … token …`; repeat with a failing Redis (stopped) to show the call returns and logs the error. Paste lines; grep the full output for the code, token, phone and email except the ADR-0026 line.
- then docs below.

## Done check (rule B1)
`uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest tests/unit`, `uv run pytest tests/e2e` (Docker; before branching, run it on `main` and record the failing test IDs: the two of I.10 if they are still there; the branch must show the same IDs and no others, and the PR lists them under "Not verified"), `uv run python -m app.cli --export-openapi --check`, `uv build`.

## Docs to update in this PR (rule E1)
- [ ] docs/features/POC-6.3/spec.md (ACs ticked)
- [ ] docs/decisions/ADR-0027 (R1)
- [ ] docs/ARCHITECTURE.md — `services/notifier.py` built; the status line and the Decided heading say ADR-0003 to ADR-0025, make it ADR-0027 and list ADR-0026 (E2, found by analyze) and ADR-0027 in Decided; `QueueUnavailableError` in the `core/queue.py` row; provider list;; "Decided"/status line if it names remaining empty modules
- [ ] docs/DOMAIN_GLOSSARY.md — "Notifier" (channels SMS, LOG, EMAIL, ALL) and "Notification channel"
- [ ] docs/RUNBOOK.md — one line: an enqueue that fails because Redis is unreachable (`QueueUnavailableError`) is logged and the other channels still run; any other queue error and any database error propagate
- [ ] scope doc row 6.3 status: a human edits the Claude Docs doc, listed in the PR body
ADR-0027 (R1) records that a service may take services instead of a session (D1).

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| Q1: the LOG channel departs from Node (no OTP in the log) | a dev loses a debug aid; 7.1 still returns the code locally | human decision at approval; the spec states it |
| A profile-read database error propagates from the notifier | 7.x route answers 500, as for any database fault | decided in R1; stated in the service docstring |
| The narrow catch misses a Redis failure mode `enqueue` does not wrap | a Redis error reaches the caller as a 500 | the R3 run with Redis stopped, and a unit case per wrapped step (pool open, `enqueue_job`) |
| Account id in logs | none: an id is not PII here, no email/phone/code/token is logged | AC5 test on the formatted line |

## Decisions owed at approval besides spec Q1
Q7: a departure from scope-doc row 6.3 ("errors logged, never raised"): a database error while reading the profile propagates; only `QueueUnavailableError` from an enqueue is logged. The reason is in the spec (no enumeration signal, no aborted transaction hidden). Write the answer in the approval note; the PR body repeats it.
Q6: `app/core/queue.py` imports `redis.exceptions` (`ConnectionError`, `TimeoutError`). `redis` is arq's hard dependency and 6.1's tests already import it, but it is not declared in `pyproject.toml`; importing it adds no package. Declaring it would be a dependency change (rule C2, ask-first file), so the plan does not. Say so in the approval note if you want it declared instead.

## Estimate
R1 M, R2 S, R3 S.

## Assumptions
Spec Q2 to Q5. The service never commits and never touches the session itself. Spec Q1 (no OTP code in the LOG channel) is the one decision a human owes; its answer is written into the spec next to the approval.

## Not covered
Callers (7.1, 7.6), delivery guarantees beyond arq's retries, de-duplication of repeated reset requests (I.8).
