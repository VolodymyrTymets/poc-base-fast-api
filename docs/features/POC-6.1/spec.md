# POC-6.1 — arq worker and QueueClient

## Problem
The API has no way to hand work to a background process. ADR-0005 chose arq on Redis and a `QueueClient` protocol so notifiers (6.3) and jobs (6.2)
have something to build on, but there is no worker, no Redis setting and no queue client. `tests/utils/queue.py` says its fake is adapted to the real protocol in this task.

## Goal / business value
Goal 1 (scaffolding: a fork gets a working worker process and a testable enqueue seam) and goal 3 (the fake queue and a real-Redis test path).

## Scope
- in: `Settings` gains the Redis connection fields (the `REDIS_*` names the env templates already carry); `QueueClient` protocol and `ArqQueueClient` in
  `app/core/queue.py`; `WorkerSettings` in `app/worker.py` (`max_tries=3`, exponential backoff helper, results not kept, JSON job serializer, JSON logging); one smoke job
  `ping` that only logs; `app.state.queue` built in `create_app`, closed in the lifespan, and a `get_queue` dependency; `FakeQueue` made to satisfy the protocol; ADR-0024 for the new top-level `app/worker.py`.
- **out (explicit):** the SMS and email jobs (6.2), `NotifierService` (6.3), the Redis read cache (9.x), Docker/compose services for the worker (11.1, 11.2), cron jobs,
  job priorities, a Redis health check on `/health`, any route that enqueues.

## Acceptance criteria
- [ ] AC1 Given Redis and a running `uv run arq app.worker.WorkerSettings`, when `ArqQueueClient.enqueue("ping")` is called from another process, then the worker's log shows the job ran.
- [ ] AC2 `WorkerSettings.max_tries == 3`, `keep_result == 0`, and its Redis settings come from `Settings` (`REDIS_HOST`, `REDIS_PORT`, optional `REDIS_PASSWORD`).
- [ ] AC3 A job that raises `Retry(defer=retry_delay(job_try))` is retried with delays that grow exponentially and is a permanent failure after 3 tries.
- [ ] AC4 The API boots and answers `/api/v1/health` with no Redis running; the pool is opened on the first `enqueue`, never at boot.
- [ ] AC5 When Redis is unreachable, `enqueue` raises (rule D5, no silent drop) after exactly one connection attempt, not after arq's default five.
- [ ] AC6 `FakeQueue` and `ArqQueueClient` both satisfy `QueueClient` (checked by mypy and a unit test).
- [ ] AC7 Job arguments cross Redis as JSON, never pickle; a kwarg starting with `_` (arq's own options) is refused by the client.
- [ ] AC8 Worker log lines are JSON and redacted by the same formatter as the API (rule P4).
- [ ] AC9 `openapi.json` unchanged.

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| Redis down at API boot | app boots (AC4) | assumption A2 |
| Redis down at worker boot | arq's own connection retries, then the process exits non-zero | arq default |
| Unknown job name enqueued | worker logs "function not found" and fails the job; not retried | arq |
| Non-JSON-serialisable argument | `enqueue` raises `TypeError` before anything is sent | json serializer |
| Duplicate `_job_id` | not exposed in 6.1 (idempotency is the job's job, ADR-0005) | scope |
| Flushed Redis | in-flight jobs are lost | ADR-0005, accepted |

## Open questions
| # | Question | Assumed answer | Needs a human? |
|---|----------|----------------|----------------|
| Q1 | Add runtime dependency `arq` (rule C2)? | Yes: ADR-0005 chose it; the approval line on the plan covers it. `redis` comes transitively; no new dev dependency (`testcontainers.community.redis` ships in the installed testcontainers; verified in R1) | yes, at approval |
| Q2 | Fail boot when Redis is down? | No, lazy pool, like `DATABASE_URL` unset | no |
| Q3 | Pickle or JSON for job payloads? | JSON: pickle from a shared Redis is code execution for anyone who can write to it | no |
| Q4 | Where does `WorkerSettings` live? | `app/worker.py`, as the scope doc and command name it, thin like `main.py`; needs ADR-0024 because rule 2 of `project-structure.md` forbids new top-level modules without one | yes, at approval (alternative: `app/workers/settings.py`, command `arq app.workers.settings.WorkerSettings`, no ADR) |
| Q5 | A job must exist for AC1 | a `ping` smoke job in `app/workers/ping.py` that logs a fixed line; 6.2 adds the real ones | no |
| Q6 | E2E Redis source | `TEST_REDIS_URL` or a `redis` testcontainer, mirroring the Postgres fixtures | no |
