# POC-6.2 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     Approved-by: -->
Approved-by: Volodymyr · 2026-11-04

Pattern followed: `app/workers/ping.py` (an `async def job(ctx, ...)` module under `workers/`, registered in `app/worker.py`), `app/worker.py` `on_startup` for what goes into `ctx`,
and the Node `background-workers/email-sender` and `sms-sender` services for the behaviour (the 6.2 log lines and the environment list). No arq API is new; `ctx` and `functions` are used as in 6.1.

## Contract changes
- boundary: none (no route). `openapi.json` unchanged.
- job payloads (persisted in Redis while queued, JSON, positional): `send_totp_code(phone, code)`, `send_password_reset(account_id, email, token)`. 6.3 and 7.x enqueue by these names and orders; a change later breaks queued jobs.
- config / dependencies: none.

## Requirements (ordered; branch `feat/POC-6.2-sms-email-jobs`, one draft PR, one commit each)

### R1 — ADR-0026, the logging exception (S)
- files: `docs/decisions/ADR-0026-worker-logs-reset-token-in-dev-envs.md` (new). Records the human decision of 2026-11-04 (Volodymyr, asked by the analyze gate): an exception to rules D8 and P4 for the `send_password_reset` job only; envs `local`, `development`, `test`; fields recipient email and reset token; why (no email provider, scope doc 6.2, the flow is finished by hand from the log); consequences (a shared `development` host shows live tokens to anyone with log access; `production` and any other env never log either; the SMS OTP code is never logged); the line format `token <value>` is deliberate and survives `redact` only because no `=` or `:` follows the key, so the ADR names that dependency.
- layer: docs.
- test: none (a decision record); R3 enforces it.
- executed how: n/a.

### R2 — send_totp_code (S)
- files: `app/workers/sms.py` (new: `mask_phone`, `send_totp_code`), `app/worker.py` (register).
- layer: workers (imports `config` only).
- test: `tests/unit/test_worker_sms.py` — masked phone for `+12125550100` is `***0100` and the full number is in no record (message and extras); the code is in no record; short or non-numeric input is `***`; two calls log twice and do not raise; each environment gives the same masked line. Through `JsonFormatter` too, so the final JSON line is checked, not only `caplog`.
- executed how: R4.

### R3 — send_password_reset (S)
- files: `app/workers/email.py` (new; the env check is explicit, `if settings.app_env in LOG_MESSAGE_ENVIRONMENTS:` with a `# WHY: ADR-0026, POC-6.2` comment on the log call), `app/worker.py` (register; update `test_worker_settings` expected `functions`).
- layer: workers.
- test: `tests/unit/test_worker_email.py` — ports the three Node cases: local, development, test log email and token; production logs account id only and neither email nor token (checked on the formatted JSON, which proves redaction does not hide a token the job meant to show in local, and that production never emits one); a repeat call logs the same line. `test_worker_settings`: `functions == [ping, send_totp_code, send_password_reset]`.
- executed how: R4.
- risk: the exception relies on `redact` not matching `token <value>`; the test is named after ADR-0026 so a future tightening of `redact` fails loudly here and the owner decides (see Risks).

### R4 — real worker end to end (M)
- files: `tests/e2e/test_worker_arq.py` (two cases using `worker_logs`: `send_password_reset` with `APP_ENV=test` shows the token; `send_totp_code` shows the masked phone and neither the full number nor the code anywhere in the captured output, arq's own lines included). `worker_logs` already pins `APP_ENV=test`; a parameter for the env is added only if AC2 needs it end to end (otherwise production is covered by R3).
- executed how (evidence, rule B1): `docker run --rm redis:7-alpine` with no volume (the untracked `dump.rdb` at the root is not touched; files are staged by path, never `git add .`); start `APP_ENV=local uv run arq app.worker.WorkerSettings`; a scratchpad snippet enqueues both jobs through `ArqQueueClient`; paste the worker's `[EMAIL] Password reset … token …` and `[SMS] … ***0100` lines. Repeat with `APP_ENV=production` for the email line. Then `uv run pytest tests/e2e/test_worker_arq.py`.

## Done check (rule B1)
`uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest tests/unit`, `uv run pytest tests/e2e` (Docker or `TEST_DATABASE_URL` and `TEST_REDIS_URL`; the two failures of issue I.10 are known on `main` and are not this task), `uv run python -m app.cli --export-openapi --check`, `uv build`.

## Docs to update in this PR (rule E1)
- [ ] docs/features/POC-6.2/spec.md (ACs ticked)
- [ ] docs/ARCHITECTURE.md — `app/worker.py`, `app/workers/` row: the two jobs built; "the SMS and email jobs come with task 6.2" reworded
- [ ] docs/RUNBOOK.md — "Today the only job is `ping`": the two jobs, what each logs per environment, that the reset token is in the log outside production-like envs
- [ ] docs/DOMAIN_GLOSSARY.md — Job row: `ping` today becomes the three jobs
- [ ] docs/decisions/ADR-0026 (R1): the exception to D8/P4
- [ ] scope doc row 6.2 / issue I.5 status: a human edits the Claude Docs doc, listed in the PR body

ADR-0026 records the exception, not a pattern (D1).

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| Reset token in clear in `development` logs (Q1); the redaction filter lets `token <value>` through | token readable by anyone with log access on a shared dev host | accepted in ADR-0026 (human decision); R3 test pins the behaviour; `production` never logs it |
| Phone or code reaching a log through arq's own lines or `extra` fields | PII leak (rules D8, P4) | R4 greps the whole captured worker output for the full number and the code |
| Redaction regex rewrites the masked phone or the email | line useless | R2/R3 assert on the formatted JSON line |
| Docker/Redis unavailable here | R4 unrun | `docker info` first; otherwise `TEST_REDIS_URL`; else listed under "Not verified" |

## Estimate
R1 S (ADR), R2 S, R3 S, R4 M.

## Assumptions
Q2 to Q4 of the spec. The jobs never raise, so no retry logic. Log text matches the Node base.

## Not covered
Notifier fan-out (6.3), enqueueing from routes (7.x), a real provider, deduplication by `_job_id`.
