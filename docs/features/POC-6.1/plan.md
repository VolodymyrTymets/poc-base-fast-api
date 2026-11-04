# POC-6.1 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     Approved-by: Volodymyr · 2026-11-04

Pattern followed: `app/core/db.py` (`create_engine` built in `create_app`, opens nothing, disposed in the lifespan; `get_session` dependency reading `app.state`),
`app/dependencies.py` for the dependency, `app/config.py` for settings, `tests/conftest.py` + `tests/utils/db.py` for the container-or-env test resource, and
`app/main.py` `run()` for `configure_logging`. The lifespan already has a comment reserving the arq pool for this task. arq API checked with Context7 (python-arq/arq) on 2026-11-04.

## Contract changes
- boundary: none (no route). `openapi.json` must not change.
- config: new env `REDIS_HOST` (default `localhost`), `REDIS_PORT` (6379), `REDIS_PASSWORD` (optional); the first two are already in both `.env*.example`.
- dependencies: runtime `arq` (Q1, needs approval, rule C2). `uv.lock` changes only through `uv add arq`.
- persisted format: job payloads in Redis are JSON `{args, kwargs}` (AC7); a fork changing it breaks queued jobs.

## Requirements (ordered; branch `feat/POC-6.1-arq-worker`, one draft PR, one commit each)

### R1 — Redis settings and the arq dependency (S)
- files: `pyproject.toml` + `uv.lock` (`uv add arq`), `app/config.py` (`redis_host`, `redis_port`, `redis_password: SecretStr | None`, blank → None as `sentry_dsn`; a helper `redis_settings()` is NOT in config: config stays arq-free), `.env.example`, `.env.development.example` (password line, commented).
- layer: config. test: `tests/unit/test_config_redis.py` (defaults, env override, blank password, bad port names the field, password never in the error).
- executed how: `uv run python -c "from app.config import Settings; print(Settings().redis_host)"` with and without `REDIS_HOST` exported.

### R2 — QueueClient protocol and ArqQueueClient (M)
- files: `app/core/queue.py` (not `app/workers/queue.py` as the scope doc says: `services` (6.3 notifier) and `dependencies` may not import `workers`, ADR-0011 rule 4; `core` is open to both; analyze block 1): `QueueClient` (Protocol: `async enqueue(job_name, *args, **kwargs) -> None`), `ArqQueueClient(settings)` (lazy pool under an `asyncio.Lock`, `RedisSettings(conn_retries=0)` (one attempt; the semantics are confirmed against the installed arq source in R1, rule D4), JSON `job_serializer`/`job_deserializer`, refuses `_`-prefixed kwargs, `close()`), `retry_delay(job_try, base=…)` exponential (`base * 2 ** (job_try - 1)`), `json_serializer`/`json_deserializer`. `tests/utils/queue.py`: docstring updated, `FakeQueue` unchanged in behaviour.
- layer: core (reads `config` only). `app/workers/` and `app/worker.py` import it.
- test: `tests/unit/test_queue.py`: protocol conformance of both, delays 1×, 2×, 4× base, serializer round trip and rejection of non-JSON, `_` kwarg refused, constructing the client opens no connection (monkeypatched `create_pool` not called), a failing `create_pool` is called exactly once and `enqueue` raises (AC5). Boundary mock is arq's `create_pool` only (testing-python rules).
- executed how: covered by R4's real-Redis run.

### R3 — WorkerSettings, ping job, entrypoint (M)
- files: `app/workers/ping.py` (`async def ping(ctx)` logs `"ping job ran"`), `app/worker.py` (`WorkerSettings`: `functions=[ping]`, `max_tries=3`, `keep_result=0`, `redis_settings` from `get_settings()`, JSON (de)serializers, `on_startup` calls `configure_logging`), `docs/decisions/ADR-0024-worker-entrypoint-module.md` (Q4), `.claude/rules/project-structure.md` layout line (ask-first path, `.claude/**`: confirm when the hook asks).
- layer: top-level entrypoint importing `workers`, `config`, `core`; nothing imports `app.worker`.
- test: `tests/unit/test_worker_settings.py`: AC2, functions registered, serializers set, nothing connects on import; after `on_startup`, a record with a phone number and a token sent through the `arq.worker` logger comes out as JSON with `[REDACTED]` (AC8; arq's CLI applies its own `dictConfig` first, so this proves `configure_logging` wins).
- executed how: see R4.

### R4 — API wiring and the real-Redis end-to-end test (M)
- files: `app/main.py` (create `ArqQueueClient(settings)` into `app.state.queue`; lifespan closes it; update the reserving comment), `app/dependencies.py` (`get_queue(request) -> QueueClient`, imports `core.queue`), `tests/conftest.py` (`redis_url` session fixture: `TEST_REDIS_URL` else `testcontainers.community.redis.RedisContainer`; the URL always selects database 15 and only that database is flushed per test, never `FLUSHALL`) , `tests/e2e/test_worker_arq.py`.
- test (e2e, real Redis, AC1/3/4/5): (a) subprocess `python -m arq app.worker.WorkerSettings` with `REDIS_*` env, enqueue `ping` through `ArqQueueClient`, wait for the JSON line `ping job ran` on its stdout, terminate it; (b) in-process burst `Worker` with a test-local job raising `Retry(defer=retry_delay(job_try))` shows 3 tries then failure; (c) `create_app` with Redis unreachable boots and answers health, then `get_queue` enqueue raises; (d) a route using `get_queue` (test-local) enqueues and the job lands.
- executed how (evidence, rule B1): scratchpad script: `docker run redis:7`, start `uv run poc-base-fast-api` and `uv run arq app.worker.WorkerSettings` with the same `REDIS_*`, call a throwaway python snippet that enqueues `ping` through `ArqQueueClient` (no route exists), paste the worker's log line and one redacted `arq.worker` line; then stop Redis and show the API still serves `/health`.
- risk: subprocess test timing; use a polling wait with a hard timeout, no sleeps.

## Done check (rule B1)
`uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest tests/unit`, `uv run pytest tests/e2e` (Docker or `TEST_DATABASE_URL` and `TEST_REDIS_URL`), `uv run python -m app.cli --export-openapi --check`, `uv build`. Whatever cannot run goes under "Not verified".

## Docs to update in this PR (rule E1)
- [x] docs/features/POC-6.1/spec.md (ACs ticked)
- [x] docs/ARCHITECTURE.md: `core/queue.py`, `workers/` and `worker.py` built; "No cache or queue is wired" reworded; ADR-0024 in Decided
- [x] docs/RUNBOOK.md: `REDIS_*`, database 15 of `TEST_REDIS_URL` is wiped by the tests, how to start the worker, the Redis test fixture and `TEST_REDIS_URL`; the "There is no cache or queue" sentence
- [x] docs/DOMAIN_GLOSSARY.md: terms "Job" and "Queue client"
- [x] docs/decisions/ADR-0024 (R3); `.claude/skills/test-conventions/SKILL.md`: the `queue` fixture note and `redis_url`
- [x] `.env.example` / `.env.development.example` (R1)

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| `testcontainers.redis` needs the `redis` package at import | fixture fails | `uv run python -c "import testcontainers.community.redis, redis; print(redis.__version__)"` after R1; a version conflict is raised as a dev-dependency approval, not pinned around |
| arq with Python 3.14 | worker will not start | `uv add arq` then `uv run arq --help` in R1, before anything else |
| arq `functions` must be non-empty, hence the `ping` job | a smoke job ships in production code | accepted, Q5; removed if 6.2 makes it redundant |
| JSON payloads limit argument types | 6.2/6.3 pass only plain values | stated in AC7 and the ADR |

## Estimate
R1 S, R2 M, R3 M, R4 M.

## Assumptions
Q1 to Q6 of the spec. Default `max_tries=3` with 1 s base backoff.

## Not covered
Real jobs, notifier, Docker services, queue metrics, Redis auth/TLS settings beyond host, port and password.
