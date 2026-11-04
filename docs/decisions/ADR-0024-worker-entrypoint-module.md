# ADR-0024 — `app/worker.py`, the arq worker entrypoint

- **Date:** 2026-11-04
- **Status:** accepted
- **Deciders:** volodymyr
- **Ticket:** POC-6.1
- **Supersedes:** nothing. It adds one file to the structure of ADR-0011 (rule 2: a new top-level module needs an ADR), as ADR-0020 did for `cli.py`.

## Context
The scope doc names the worker command `uv run arq app.worker.WorkerSettings` and the file `app/worker.py`. arq loads the settings class by import path.
`app/workers/` is the home of the jobs, and ADR-0005 keeps the worker a separate process from the API.

## Decision
- `app/worker.py` holds `WorkerSettings` and its startup hook only. It may import `config`, `core` and `workers`; nothing in `app/` imports it.
- Jobs live in `app/workers/<job>.py`; a new job is added to `WorkerSettings.functions`.
- The `QueueClient` protocol, `ArqQueueClient`, the JSON serializers and `retry_delay` live in `app/core/queue.py`, not in `workers/`, because services
  (the notifier, task 6.3) and `dependencies` may import `core` but not `workers` (ADR-0011 rule 4). The scope doc's `app/workers/queue.py` is superseded by this.
- Job payloads are JSON, never pickle: a Redis that anyone can write to would otherwise run code in the worker.

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| `app/workers/settings.py` and `arq app.workers.settings.WorkerSettings` | works without an ADR, but departs from the command the scope doc and the team already use |
| Protocol in `app/workers/queue.py` | the notifier service would have to import `workers`, against ADR-0011 rule 4 |
| arq's default pickle serializer | code execution through Redis |

## Consequences
- Positive: the documented command works; the seam a notifier depends on sits in `core`.
- Accepted cost: one more top-level file; job arguments are limited to JSON types.

## Revisit when
The worker needs more than one settings class (several queues), or jobs need a type other than JSON.
