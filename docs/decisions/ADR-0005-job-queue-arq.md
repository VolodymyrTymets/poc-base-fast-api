# ADR-0005 — arq as the background job queue

- **Date:** 2026-10-29
- **Status:** accepted
- **Deciders:** volodymyr
- **Ticket:** POC-1.1
- **Supersedes:** Node ADR-0005 (BullMQ background jobs as a separate Nest application). Decision D4 of the scope doc.

## Context
The Node base runs a second application that consumes BullMQ queues on Redis (`sms-sender`, `email-sender`). Redis is already
part of the stack. The Python base needs the same shape: the API enqueues, a separate process consumes.

## Decision
- Jobs run on arq (asyncio on Redis), in a worker process separate from the API.
- Retries: `max_tries` is a worker setting (the library default is 5). arq has no backoff setting; a job raises `Retry(defer=...)` with a delay computed from `ctx['job_try']`. The scope doc's "exponential backoff" is therefore written in the job, not configured. (Source: arq documentation, retrying jobs; checked with Context7 on 2026-10-29.)
- Notifiers receive a small `QueueClient` protocol, not arq directly, so tests inject a fake that captures jobs.
- Jobs are idempotent. At this stage they only log (no SMS or email provider). Rule P4 forbids tokens and phone numbers in logs, so this ADR does not log them. The scope doc's log-only password-reset flow (task 6.2, and the runbook's "forgot password" step) needs the token to be visible locally; that needs an explicit local-only exception to P4, which is a human decision (rule F2) and is not made here.

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| Celery | sync-first, heavier than an asyncio service needs |
| Dramatiq | async support is a middleware add-on, while arq is asyncio-first and smaller |
| FastAPI `BackgroundTasks` | in-process and not durable: a restart loses the job |

## Consequences
- Positive: Redis is already in the stack; small API surface.
- Accepted cost: arq's retry model is manual. Flushing Redis also drops in-flight jobs, as in the Node base.
- Follow-ups: tasks 6.1 to 6.3.

## Revisit when
Jobs need scheduling beyond arq's cron, priorities, or a broker other than Redis.
