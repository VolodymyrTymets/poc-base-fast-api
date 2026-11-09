# Runbook

> How to run this project, and what goes wrong. Written for a human joining on day one — and read by the agent when the environment misbehaves.

## First run
The order matters: **database, then migrate, then seed, then start.** Each step needs the one before it.

```bash
# 0. prerequisites: uv (>= 0.12), Docker (or any PostGIS server), network access for the first interpreter download.
#    Python 3.14 is pinned in .python-version; uv fetches it if it is missing.
uv sync                      # creates .venv from uv.lock
cp .env.example .env         # every setting has a default; see the file for the variables

# 1. a PostGIS database. Skip the container if you already have a PostGIS server; use a database of its own, not
#    the image's default `postgres` one (see "Common failures").
#    `127.0.0.1:` makes Docker fail loudly when a Postgres already listens on 5432 (see "Common failures"); without it the
#    container starts anyway and `localhost:5432` keeps reaching the other server. If it fails, use another port (for example
#    `127.0.0.1:5433:5432`) and put the same port in DATABASE_URL below.
docker run -d --name poc-base-pg -e POSTGRES_PASSWORD=postgres -p 127.0.0.1:5432:5432 postgis/postgis:16-3.4
docker exec poc-base-pg psql -U postgres -c 'CREATE DATABASE poc'
#    .env.example already holds the matching line, so the copied .env works as it is:
#    DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/poc

# 2. the schema: the tables, the enum types, the postgis extension and SeedHistory (see "Migrations")
uv run alembic upgrade head

# 3. the base data: the roles CUSTOMER and ADMIN (see "Seeds"). Safe to repeat; a second run does nothing.
uv run python -m app.seeds   # exit 0 when done

# 4. the API, on PORT (default 3001)
uv run poc-base-fast-api
curl localhost:3001/api/v1/health    # {"status":"ok"}
```
Step 3 is not strictly needed: with `DATABASE_URL` set, step 4 runs the same seeds before it serves. Run it by hand the first time anyway,
because it reports a seed problem on its own, with an exit status, instead of as a failed startup. Step 4 stops at startup, and does not
serve, when the database is unreachable, was never migrated (`relation "SeedHistory" does not exist`: go back to step 2) or a seed fails.
After a `git pull` that adds a migration, run steps 2 and 3 again before starting.

`DATABASE_URL` (`postgresql+asyncpg://...`, nothing else is accepted) is optional: unset or blank, steps 1 to 3 do not apply, the server still
boots and `/api/v1/health` answers, and only a route that needs a database session fails. The read cache needs Redis only when it is on (see "Read cache"). `uv build` writes the
wheel and sdist into `dist/` (gitignored). Settings come from the environment first and `.env` second; `.env.development.example` is the
same file for a shared development host. A bad value (for example `PORT=abc`) stops the boot and names the field.

## Token secrets
`JWT_SECRET` (access tokens) and `JWT_REFRESH_TOKEN_SECRET` (refresh tokens) sign the JWTs; `JWT_ACCESS_TOKEN_EXPIRES_IN` (default `15m`) and
`JWT_REFRESH_TOKEN_EXPIRES_IN` (default `7d`) take `30s`, `15m`, `55min`, `2h` or `7d`. With `APP_ENV` `local` or `test` they may be unset: the
app boots and only issuing or checking a token fails (500). With `development` or `production` the boot stops unless both are set, at least
32 characters and different, so `.env.development.example` must be edited before use (`openssl rand -hex 32` makes a good value). Changing a
secret logs everyone out.

## Logging, errors and shutdown
- Logs are one JSON object per line on stdout, uvicorn's included. `LOG_LEVEL` sets the level. Tokens, passwords, DOB and
  phone numbers are replaced by `[REDACTED]`; this is best effort (rule P4), so still never log a secret.
- **Request id (task 11.6, ADR-0033):** every response has an `X-Request-ID` header. Send your own (1 to 64 characters of letters, digits, `.`, `_`, `-`) and it is echoed; otherwise one is generated, and a malformed one is replaced and never logged. Every JSON log line written while the request is handled, uvicorn's access line included, has the same `request_id`, so `grep '"request_id": "abc-123"'` follows one request. A line outside a request, such as start-up, has none. An unhandled 500 carries the id in the header and in its `unhandled error` log line, but not on uvicorn's access line or its `Exception in ASGI application` traceback line for it (those are written outside the request, after the id is reset): grep the id, then read the lines next to the `unhandled error` one. Worker jobs do not carry the id yet.
- **Security headers (task 11.6):** every response the app sends has `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` and `Cache-Control: no-store`. An unhandled 500 does not (Starlette answers it outside the middleware, the same limit as CORS: `docs/api/ERRORS.md`). No HSTS and no Content-Security-Policy are sent: the app speaks plain HTTP behind whatever ends TLS, which sets HSTS, and the Swagger UI loads a script from a CDN.
- Sentry starts only when `APP_ENV` is not `local` and `SENTRY_DSN` is set; with no DSN nothing is sent. See ADR-0013.
- Redaction and the JSON format are set up by `uv run poc-base-fast-api` (`app.main:run`). Starting the app another way, for example
  `uvicorn app.main:create_app --factory`, skips them; a container command must use the console script, as the image of task 11.1 does (see "Docker").
- A request body over `MAX_REQUEST_BODY_BYTES` (12 MiB by default) is answered 413 with the standard error body.
- Upload limits (task 8.1): `FILE_MAX_SIZE` (bytes, default 10485760) and `FILE_ALLOWED_MIME_TYPES` (comma-separated, default `image/jpeg,image/png`, compared case-insensitively). A blank list stops the boot and names the field. Keep `FILE_MAX_SIZE` below `MAX_REQUEST_BODY_BYTES`: a body over that is answered 413 by the middleware before the check runs.
- `kill -TERM <pid>` (or Ctrl-C) stops accepting connections, lets in-flight requests finish for up to
  `SHUTDOWN_TIMEOUT_SECONDS` (10), runs the lifespan shutdown, then ends with the SIGTERM status (143 in a shell). That is how
  uvicorn behaves, not a crash.

## Test levels and markers
Three levels (ADR-0029): `tests/unit` (nothing outside the process), `tests/integration/db` and `tests/integration/http` (a real Postgres, the app in process) and `tests/e2e` (the app, the worker or a command as its own process).
Markers are set by the folder and the fixtures a test uses; nothing to write in a test file. A test outside those folders stops the run.
| Command | Runs | Needs |
|---------|------|-------|
| `uv run pytest -m unit` (or `tests/unit`) | the fast tier, for every save | nothing |
| `uv run pytest -m "not db and not redis"` | unit plus the integration and e2e tests that need neither | nothing (no Docker) |
| `uv run pytest -m "not e2e"` | unit and integration, before a push | Docker or `TEST_DATABASE_URL` |
| `uv run pytest -m "integration and http"` | the endpoint tests | Docker, except the few with no database |
| `uv run pytest -m db` / `-m redis` | everything that touches Postgres / Redis | Docker or the `TEST_*` URLs |
| `uv run pytest tests/e2e` | process-level tests (server shutdown, worker, `python -m app.seeds`) | Docker, Redis |
Markers: `unit`, `integration`, `e2e`, `db`, `http`, `redis` (descriptions in `pyproject.toml`; `--strict-markers` is on). `-ra` prints a reason line for every test that did not pass.

## Database tests
The database tests run against a real Postgres (rule P8, ADR-0006). Where it comes from:
- **Docker (default):** with `TEST_DATABASE_URL` unset, the first database test starts one `postgis/postgis:16-3.4` container
  (testcontainers) and removes it when the session ends. Docker must be running; otherwise those tests fail with a message naming Docker
  and `TEST_DATABASE_URL`. They are never skipped.
- **An existing server:** set `TEST_DATABASE_URL` (`postgresql+asyncpg://...`) in `.env.test` (copy `.env.test.example`, gitignored) or export it;
  the variable wins over the file. No container is started. The role needs `CREATEDB` and, for the `postgis` extension, superuser rights.

On that server the suite builds one template database per session with `alembic upgrade head` (`poc_test_template_<hex>`, with the seeds run on it) and gives each test module a copy of it (`poc_test_module_<hex>`, made with `CREATE DATABASE ... TEMPLATE`, dropped after the
module). Fixtures in `tests/conftest.py`: `database_url` (the server), `template_database`, `module_database_url`, `db_engine` (the app's
engine on the module's database; commits stay for the module, so use it for checks across connections) and `db_session` (rolled back after
each test, commits included; the default for a test that writes rows).
The fixtures of `tests/conftest.py` only ever drop databases whose name starts with `poc_test_`; `tests/integration/db/test_db_migrations.py` drops its own
`poc_migrations_*` databases on the same server. A killed run can leave either kind on an existing server: drop it by hand. A container is
reaped by testcontainers.

The older tests `test_db_account_models.py`, `test_db_file_models.py`, `test_db_mixins.py` and `test_db_session.py` still make their own
schema or tables on the server `database_url` gives, and drop only those. Postgres time zone does not matter: the app's engine sets the
session to UTC.

## HTTP tests
Which level and which fixture to use, with a unit and an integration example, is in the `test-conventions` skill (`.claude/skills/test-conventions/SKILL.md`).

Fixtures in `tests/conftest.py`, helpers in `tests/utils/` (task 3.2):
- `asgi_app`: the real app from `create_app`, on the module's database. A test may add routes to it (`@asgi_app.get(...)`); they live for that test only.
- `client`: an httpx `AsyncClient` on `asgi_app` with the lifespan started before the test and stopped after it (`ASGITransport` does not run
  it by itself). It needs a database (Docker or `TEST_DATABASE_URL`). A test with no database uses `running_client(create_app(Settings()))`
  from `utils.client`; `client_for(app)` is the same client without the lifespan.
- `utils.auth`: `sign_up(client, email, password)` and `sign_in(...)` post to `/api/v1/auth/sign-up` (expects 201) and `/sign-in` (expects 200) and
  return `AuthTokens`; `.headers` is the Bearer header, `.refresh_headers` the `x-refresh-token` one. A wrong status fails the test with the status
  and the start of the body. Since task 7.3 they call the real routes; the app in the test needs token secrets (`Settings(app_env="test", jwt_secret=..., jwt_refresh_token_secret=...)`, `utils.jwt`), which the default `asgi_app` does not have.
- `queue`: a `FakeQueue` that records `enqueue(job_name, *args, **kwargs)` calls (`jobs`, `named(name)`, `clear()`) and never touches Redis. It satisfies the
  `QueueClient` protocol of `app/core/queue.py`; to use it through the app, `asgi_app.dependency_overrides[get_queue] = lambda: queue`. A service is swappable the same way (`dependency_overrides[get_account_service]`, ADR-0025), but only for one that fronts an external edge or to test the wiring itself: data-layer behaviour is still tested on the real database (rule P8).
- `frozen_clock`: stops the process clock at `FROZEN_NOW` (2026-01-01 12:00 UTC); `frozen_clock.shift(timedelta(...))` moves it. Use it to
  expire a token or code instead of sleeping. `datetime.now(UTC)` and `utc_now()` (the same instant, naive) follow it; `time.monotonic` does not.
  **It moves this process only:** a database default such as `CURRENT_TIMESTAMP` still reads Postgres's clock, so code under test must pass `utc_now()`.
  List `frozen_clock` after the database fixtures in a test's arguments: the first database test of a session starts the container and
  builds the template, and that wait should run on the real clock.

## Redis, the queue and the worker
The API enqueues jobs and a separate process runs them (ADR-0005, ADR-0024). Settings: `REDIS_HOST` (default `localhost`), `REDIS_PORT` (6379),
`REDIS_DATABASE` (0) and an optional `REDIS_PASSWORD`. The API needs no Redis to boot: the connection opens on the first enqueue, and an enqueue with Redis
down fails at once. Start a Redis (for example `docker run -d --name poc-base-redis -p 127.0.0.1:6379:6379 redis:7-alpine`), then the worker, which needs the same
`REDIS_*` values as the API:
```bash
uv run arq app.worker.WorkerSettings    # logs JSON on stdout; SIGTERM or Ctrl-C lets a running job finish
```
Jobs today: `ping` (logs `ping job ran`), `send_totp_code(phone, code)` (logs `[SMS] TOTP code sent to ***0001`: last four digits of the phone, the code never) and `send_password_reset(account_id, email, token)` (task 6.2, log only). The reset job logs `[EMAIL] Password reset for <email> (account <id>): token <token>` only when `APP_ENV` is `local`, `development` or `test`, so the flow can be finished by hand from the worker log (ADR-0026: anyone who can read the logs of a shared `development` host can read live tokens); any other environment logs the account id only. A job is tried at most 3 times (`Retry(defer=retry_delay(ctx["job_try"]))`
doubles the wait from 5 s); results are not kept. Job arguments must be JSON values. arq's own first two start-up lines are plain text (its CLI prints them before our hook runs).
Flushing Redis drops queued and in-flight jobs.

The notifier (task 6.3) enqueues those jobs by channel. An enqueue that fails because Redis is unreachable (`QueueUnavailableError`) is logged as `could not queue <job> for account <id>` and the other channels still run; any other queue error and any database error propagate. Nothing there logs a code, a token, an email or a phone number.

**Redis in the tests** (`tests/e2e/test_worker_arq.py`, marker `redis`): with `TEST_REDIS_URL` unset, the first such test starts one `redis:7-alpine` container (testcontainers) for the session;
set `TEST_REDIS_URL` (a `redis://` URL with host and port, in `.env.test` or exported) to use an existing server instead. The tests use database index 15 only and flush only that
index, whatever the URL says, so a developer's default database and queue are left alone. Without Docker and without the variable the tests fail with a message; they never skip.

## Read cache
The API caches two reads in the Redis the queue uses (task 9.2, ADR-0035): the account with its profile (`GET /api/v1/account`) and the roles `require_roles` checks. An entry lives 60 seconds. `CACHE_ENABLED` (default `true`; `false` sends every read to the database) is the only setting; it uses `REDIS_*`.
- **What is stored:** keys `cache*Account*<sha256>` and `cache*AccountRole*<sha256>`, values are JSON. The account value holds the profile, so email, phone number and date of birth are in Redis for up to 60 seconds: do not expose that Redis to a network.
- **Redis down:** reads still answer from the database; the log has one `read cache read failed: ConnectionError` warning per request (no key, no value), and a request pays at most a 1 second connect timeout. A wrong `REDIS_PASSWORD` is not an outage: it fails the request with the error.
- **After a write:** `PATCH /api/v1/accounts/{accountId}/profile` removes every `cache*Account*` key after it commits, so the next `GET /account` reads the database. Anything that changes the data another way (SQL by hand, a seed) leaves the entry for up to 60 seconds.
- **Look and flush by hand:** `redis-cli --scan --pattern 'cache*'`, then `redis-cli ttl <key>`; delete by pattern, for example `redis-cli --scan --pattern 'cache\*Account\**' | xargs redis-cli unlink`. Never `FLUSHALL` or `FLUSHDB` on the queue's database: it drops queued jobs. Never `KEYS` on a busy server.
- **Tests:** the test environment sets `CACHE_ENABLED=false`; `tests/integration/http/test_http_read_cache.py` turns it on with the test Redis (index 15, the `redis_settings` fixture) and proves a hit by counting the statements the app's engine runs.

## Sign-in code (OTP)
`POST /api/v1/auth/otp/request` with `{"phoneNumber": "+12125550142"}` (task 7.1) answers `{"success": true, "code": "123456"}`. An unknown number becomes a customer account;
a known one gets a new code that replaces the old. The code is stored only as an Argon2id hash (ADR-0028) and is valid for 2 minutes. The SMS job is queued after the database commit,
and the worker logs `[SMS] TOTP code sent to ***0142` (last four digits, never the code). `code` is in the body only for `APP_ENV` `local`, `development` and `test`; in `production` the key is absent.
With Redis down the call still answers 200 and the server logs `could not queue send_totp_code for account <id>`. The endpoint is not rate limited (issue I.8).

`POST /api/v1/auth/otp/verify` with `{"phoneNumber": "+12125550142", "code": "123456"}` (task 7.2) answers `{"accessToken": "...", "refreshToken": "..."}`; `Authorization: Bearer <accessToken>` then opens `GET /api/v1/account`.
A wrong, expired (2 minutes) or already used code, or an unknown number, is 401 `INVALID_CREDENTIALS` with one body for all. A success clears the code, sets `isPhoneVerified` and stores the sha256 of the refresh token (ADR-0008), replacing the previous one.
The endpoint is not rate limited and a code has 10^6 values (issue I.8, ADR-0028). Every verify call, even for an unknown number, runs one Argon2 check; the route ends its read transaction first, so no pooled connection is held while it runs and a flood of calls costs CPU and memory, not pool slots (`test_no_pooled_connection_is_held_while_the_code_is_hashed`).

## Sign up and sign in with a password
`POST /api/v1/auth/sign-up` with `{"email": "a@example.com", "password": "correct-horse-battery"}` (task 7.3) answers 201 `{"accessToken": "...", "refreshToken": "..."}` and creates a customer account.
`POST /api/v1/auth/sign-in` with the same body answers 200 with a new pair; the new refresh token replaces the stored sha256, so the previous one stops matching (ADR-0008).
The email is lowercased before lookup and storage. An email already on any profile, a soft-deleted one included, is 409 `EMAIL_ALREADY_REGISTERED`. An unknown email, a wrong password, an account made by OTP
that has no password, and a soft-deleted account or identity are one 401 `INVALID_CREDENTIALS`. The password is stored as an Argon2id hash (ADR-0028) in `AccountIdentity.hash`; `salt` stays null because the salt is inside the hash.
A password is 8 to 72 bytes on sign-up and 1 to 72 on sign-in. Neither route is rate limited (issue I.8); each runs one Argon2 hash or check and holds no pooled connection while it does.

## Forgot password
`POST /api/v1/auth/password/restore` with `{"email": "a@example.com"}` (task 7.6) answers 200 `{"success": true}` for every well-formed email, registered or not, and the body never holds the token. For a registered account it stores the sha256 of a random 32-byte token valid for 30 minutes
(a new request replaces it) and queues the `send_password_reset` job after the commit. With no email provider the worker logs it, so finish the flow by hand:
```bash
curl -X POST localhost:3001/api/v1/auth/password/restore -H 'content-type: application/json' -d '{"email": "a@example.com"}'
# the worker log (uv run arq app.worker.WorkerSettings) shows: [EMAIL] Password reset for a@example.com (account <id>): token <64 hex characters>
curl -X POST localhost:3001/api/v1/auth/password/reset -H 'content-type: application/json' -d '{"token": "<64 hex characters>", "newPassword": "a-new-password"}'   # 204
```
The worker prints the token only for `APP_ENV` `local`, `development` and `test` (ADR-0026); anywhere else it logs the account id only. Redis must be up for the job to be queued: with Redis down the call still answers 200 and the server logs `could not queue send_password_reset`.
`reset` answers 204 with no body. The new password is stored as an Argon2id hash and, in the same UPDATE, the refresh token, the reset token and any pending sign-in code are cleared: the old password and every refresh token issued before stop working. An unknown, used, expired or soft-deleted-account token is one 400 `INVALID_RESET_TOKEN`;
a token works once, and of two resets racing with it one applies. An account made by OTP, which has no password, sets its first one this way (the account needs an email on its profile). Neither route is rate limited (issue I.8): a known email can have its pending token replaced by anyone, and response time can tell known from unknown emails.

## Change password
`POST /api/v1/auth/password/change` with `Authorization: Bearer <accessToken>` and `{"currentPassword": "...", "newPassword": "..."}` (task 7.5) answers 204 with no body. The new password is stored as an Argon2id hash and, in the same UPDATE,
the refresh token, any pending reset token and any pending sign-in code are cleared: the old password and every refresh token issued before stop working (one narrow exception: a sign-in that checked the old password just before the change can still finish after it and store a refresh token; see ENDPOINTS.md `changePassword`), and the account signs in again once its access token expires (default 15 minutes; that token is not revoked).
A wrong current password, an account that has no password (made by OTP), and a soft-deleted account are one 401 `INVALID_CREDENTIALS`; a bad or missing Bearer token is 401 `UNAUTHORIZED`, also when the body is invalid. Two changes racing from the same stored hash apply one;
the other is 401. The new password is 8 to 72 bytes with no control characters; it may equal the current one. The route is not rate limited (issue I.8), and each call runs two Argon2 steps with no pooled connection held.

## Refresh and sign out
`POST /api/v1/auth/refresh` with the header `x-refresh-token: <refreshToken>` and no body (task 7.4) answers 200 `{"accessToken": "...", "refreshToken": "..."}`. The refresh token is single use: the new one replaces the stored sha256,
so the old one answers 401 `UNAUTHORIZED` at once, and so does one issued before a later sign-in or a sign-out. Two requests with the same token get one 200 and one 401. A missing, malformed, expired or tampered token, an access token in the
header, and a soft-deleted account are the same 401 `UNAUTHORIZED`, which is what tells a client to sign in again.
`POST /api/v1/auth/sign-out` with `Authorization: Bearer <accessToken>` answers 204 with no body: it clears the stored refresh hash and any pending sign-in code (the password stays). It is idempotent: a second call, or an account
with nothing stored, is 204. The access token is not revoked and works until it expires (default 15 minutes); there is no denylist.

## Files
Four routes (tasks 8.2 and 8.3, ADR-0009), all with `Authorization: Bearer <accessToken>`. Only the content route returns the bytes.
```bash
curl -X POST localhost:3001/api/v1/files -H "Authorization: Bearer $TOKEN" -F 'file=@photo.png;type=image/png' -F name=Holiday   # 201 {id, name, mimeType, size, createdAt, contentUrl}
curl -X PATCH localhost:3001/api/v1/files/$ID -H "Authorization: Bearer $TOKEN" -F name=Renamed                                  # 200; add -F 'file=@new.jpg;type=image/jpeg' to replace the bytes
curl localhost:3001/api/v1/files/$ID -H "Authorization: Bearer $TOKEN"                                                            # 200, metadata
curl -o out.png localhost:3001/api/v1/files/$ID/content -H "Authorization: Bearer $TOKEN"                                        # 200, the bytes; `cmp photo.png out.png` is silent when they match
```
The size is the number of bytes received and the mime type is the one the upload declares; `image/jpeg` and `image/png` by default (`FILE_ALLOWED_MIME_TYPES`). An upload over `FILE_MAX_SIZE` is 413 and a disallowed or missing type is 422, both `VALIDATION_FAILED` with `file` in `details`, and nothing is stored; a body over `MAX_REQUEST_BODY_BYTES` is 413 before routing. An unknown id, another account's file and a soft-deleted file are the same 403 `FORBIDDEN`. Without `name` the name is the upload's filename (`null` when that is over 255 characters or has control characters). The form is parsed before the handler runs, so one request can hold up to `MAX_REQUEST_BODY_BYTES` in memory.
The content route (task 8.3) reads the whole value from the database and answers with `Content-Type` (the stored mime type; `application/octet-stream` when it is null), `Content-Length` and `X-Content-Type-Options: nosniff`; a row with no stored bytes is 404 `NOT_FOUND`, and an unknown, foreign or soft-deleted file is the same 403 as for the metadata. It sends no `Content-Disposition`, so a browser renders what the type allows: with the default jpeg and png list that is an image, but a fork that adds `text/html` or `image/svg+xml` (an image that runs script when rendered inline) to `FILE_ALLOWED_MIME_TYPES` would serve uploaded pages or scripts inline under the API origin, and must add `Content-Disposition: attachment` (or a `sandbox` Content-Security-Policy) to the route first. The bytes cannot go straight into an `<img src>`, which sends no Bearer token: fetch them as a blob.

## Seeds
Seed items are the base data the app creates for itself: the two roles (`CUSTOMER`, `ADMIN`) everywhere, and for `APP_ENV` `local`, `development` and `test` also (task 5.5) a sample admin (`+12125550100`, `admin+d1@example.com`, `Admin User`, role `ADMIN`) and three sample customers (`+12125550101` to `+12125550103`, emails `customer+d1@example.com` to `customer+d3@example.com`, role `CUSTOMER`). The phones are in the range reserved for fiction and none of them has a password: they are meant for OTP sign-in. `production` gets the roles only; a fork that needs a production admin adds its own seed item with its own phone.
- With `DATABASE_URL` set, the app runs them on startup, before it serves. Each item runs in its own transaction and is recorded in `SeedHistory`;
  one that has nothing to do (the roles already exist) is skipped. A second start adds nothing. The customer item creates only the sample phones that have no account yet, so it also runs on a database that already has the admin.
- `uv run python -m app.seeds` runs the same items and exits: 0 when done, 1 without `DATABASE_URL` or when an item fails. The development list
  (sample data) is used for `APP_ENV` `local`, `development` and `test`, never for `production`.
- **A failed seed stops the boot** (decision of POC-5.1), and so does an unreachable database or one that was never migrated (`relation "SeedHistory"
  does not exist`: run `uv run alembic upgrade head`). Without `DATABASE_URL` the app still boots. The failure is in `SeedHistory`
  (`select name, successful, result from "SeedHistory"`); fix the cause and start again, the same row is updated and the item runs again.
- Two instances starting together take turns (an advisory lock), so nothing is seeded twice.
- In tests the template database is already seeded. A test of the seeds themselves takes `unseeded_database_url` (a migrated, empty database, one per
  test) and `unseeded_session_factory` from `tests/conftest.py`; it never deletes rows to get there.

## Migrations
Alembic (ADR-0004, ADR-0017): `alembic.ini` and `migrations/` at the repo root; revision `0001_init` is the final state of the
Node base's four Prisma migrations, and `0002_seed_history` adds the `SeedHistory` table of the seed runner (task 5.1;
`uv run alembic downgrade 0001_init` removes only it, and the seed history with it). The database URL is read from `DATABASE_URL` (environment first, then `.env`), never from `alembic.ini`.
- `uv run alembic upgrade head` builds the schema on an empty database; `uv run alembic check` fails if the models and the revisions
  differ; `uv run alembic downgrade base` removes the tables and the two enum types and leaves the `postgis` extension (the rows are gone for good).
- `uv run alembic upgrade head --sql` prints the SQL without connecting (it still needs `DATABASE_URL`, to pick the dialect).
- The first revision runs `CREATE EXTENSION IF NOT EXISTS "postgis"`: the server needs the PostGIS files installed and the role must be
  allowed to create the extension (a superuser in practice). The `postgis/postgis` image has both.
- Point `DATABASE_URL` at the database you mean: `.env` is read when the variable is not exported, so check which one a bare
  `alembic upgrade head` will hit before running it.
- A schema change is a new hand-written revision (`uv run alembic revision -m "<what>"`, then fill in `upgrade` and `downgrade`); an applied revision is never edited. Run `alembic check` after a model change: it names what the revision is missing.
- The tests in `tests/integration/db/test_db_migrations.py` create a database named `poc_migrations_<hex>` on the test server ("Database tests" above) for each
  test and drop it afterwards, so that role needs `CREATEDB` (and, for the extension, superuser rights). If a run is killed, drop any leftover `poc_migrations_*` database by hand.

## API contract
The OpenAPI document is committed as `openapi.json` at the repo root (ADR-0003). It is generated, never edited by hand:
- `uv run python -m app.cli --export-openapi` rewrites it from `create_app()`; the output is sorted and stable, so a second run changes nothing.
- `uv run python -m app.cli --export-openapi --check` exits 1 without writing when the file is stale. `tests/unit/test_openapi_stale.py` does the same check, so
  a route added without regenerating fails `uv run pytest tests/unit`.
- `/docs` (Swagger UI), `/redoc` and `/openapi.json` are served by the running app for `APP_ENV` `local` and `development` only and list the six feature tags; with `test` or `production` they answer 404 (task 11.6, ADR-0033). The export command above works in every environment: it does not use the served route.

## Docker
One `Dockerfile` at the repo root, two targets (task 11.1, ADR-0030): `development` (the API, with the dev group and `tests/`) and `worker`. Both need `DATABASE_URL`; the worker needs `REDIS_*`. Nothing secret is in the image: pass settings with `-e` or `--env-file` at run time.
```bash
docker build --target development -t poc-api .
docker build --target worker -t poc-worker .

# a PostGIS database, then the API on the host's 3077 (host.docker.internal reaches the host's published port)
docker run -d --name poc-api --add-host=host.docker.internal:host-gateway -p 3077:3001 \
  -e DATABASE_URL=postgresql+asyncpg://postgres:postgres@host.docker.internal:5432/poc poc-api
curl localhost:3077/api/v1/health        # {"status":"ok"}
docker stop poc-api                      # graceful; the exit status is 0 (143 under an init process, 137 means killed)
```
- The entrypoint waits for Postgres (`DB_WAIT_ATTEMPTS`, default 30, `DB_WAIT_INTERVAL_SECONDS`, default 1; it prints `attempt i/N failed: <ExceptionClass>` and gives up with exit 1; each attempt can take up to 5 s when packets are dropped, so the worst case is about 3 minutes; a `DATABASE_URL` that is not `postgresql+asyncpg://` is exit 2 at once), then runs `alembic upgrade head` and `python -m app.seeds`, then the command. `RUN_MIGRATIONS=0` skips the migrate and seed steps; the `worker` target sets it, so only the API container owns the schema.
- A failed migration or seed ends the container with a non-zero status and the server never starts (for example, a Postgres without PostGIS: `extension "postgis" is not available`). Read it with `docker logs`.
- The image does not set `APP_ENV`, so it is `local`: the sample admin and customers are seeded, the OTP `code` is in the response body and the worker logs reset tokens. Pass `-e APP_ENV=...` (and, for `development` or `production`, the JWT secrets) for anything shared.
- The image sets `HOST=0.0.0.0`; outside a container `HOST` stays `127.0.0.1`. `docker run <image> sh` still waits and migrates first; use `--entrypoint sh` to skip that.
- Tests: `tests/e2e/test_docker_image.py` builds both targets and runs them against the test Postgres (and Redis for the worker); it needs Docker, so it is selected by `-m db` and never by `-m "not db and not redis"`.

## Docker Compose
`docker-compose.yml` starts four services (task 11.2, ADR-0031): `db` (PostGIS), `redis`, `api` and `worker`, built from the image of the previous section. The containers read `.env.development`; the root `.env` only sets the published host ports.
```bash
cp .env.development.example .env.development   # gitignored
# edit it: set JWT_SECRET and JWT_REFRESH_TOKEN_SECRET to two different values of 32+ characters (openssl rand -hex 32),
# and keep POSTGRES_PASSWORD equal to the password in DATABASE_URL
docker compose up -d --build
docker compose ps                              # db and redis healthy, api and worker running
curl localhost:3001/api/v1/health              # {"status":"ok"}
docker compose logs -f worker                  # the job log, for example the [SMS] and [EMAIL] lines
docker compose down                            # keeps the data; adding the volumes flag deletes the database and the queue
```
- `api` and `worker` stop at boot with `jwt_secret must be at least 32 characters` while the placeholder secrets are in place: `APP_ENV=development` checks them (see "Token secrets").
- `api` migrates and seeds, `worker` never does (ADR-0030). The stack needs Docker only; the host needs no Python.
- **A second stack** runs beside the first from a second checkout or worktree (compose names the project after the directory):
  ```bash
  git worktree add ../poc-base-fast-api-2
  ./move-env.sh ../poc-base-fast-api-2           # copies .env, .env.development, .env.test that exist; refuses to overwrite one there unless --force
  cd ../poc-base-fast-api-2 && ./set-ports.sh 4000   # API 4000, Postgres 4001, Redis 4002
  docker compose up -d --build
  curl localhost:4000/api/v1/health
  ```
  `set-ports.sh` writes the three `EXPOSE_*` ports to `.env`, and also `PORT`, `REDIS_PORT` and the port of `DATABASE_URL` there for a run outside Docker. Container-internal ports stay 3001, 5432 and 6379. Because `PORT` in `.env` becomes the published port, a local `uv run poc-base-fast-api` and the `api` container cannot share a checkout at once.
  A published port already in use on the host fails `up` with a bind error: pick another base.
- The stack is local-only: ports are published on `127.0.0.1` (`EXPOSE_HOST`, in `.env` or the shell, changes that). With `APP_ENV=development` the API returns OTP codes and has a seeded admin, and Redis has no password, so do not open the ports to a network, and change the `change-me` database password if you do.
- `move-env.sh <dir>` takes a path relative to where you run it and refuses to target its own checkout.
- On Apple Silicon `db` runs under emulation and Docker prints a platform warning; it still becomes healthy.

## Commands
See the command map in `CLAUDE.md` — that is the canonical list: `uv run ruff check .`, `uv run ruff format --check .`,
`uv run mypy`, `uv run pytest tests/unit`, `uv run pytest tests/integration`, `uv run pytest tests/e2e`, `uv run poc-base-fast-api`, `uv run alembic upgrade head` and
`uv run alembic check`. Coverage is a diagnostic, run by hand with `uv run pytest --cov=app`.

## Undocumented steps everyone knows
- The first `uv sync` downloads Python 3.14 if no matching interpreter is installed.
- `uv.lock` is regenerated by `uv`; never edit or delete it by hand (rule T3).

## Common failures
| Symptom | Cause | Fix |
|---------|-------|-----|
| `alembic` prints `FAILED: DATABASE_URL is not set` | no `DATABASE_URL` in the environment or in `.env` of the current directory | export it, or run from the repo root where `.env` lives |
| `extension "postgis" is not available` (or permission denied to create it) | the server has no PostGIS files, or the role is not a superuser | use a PostGIS server (the `postgis/postgis` image) and a role that may create extensions |
| `alembic check` lists tables such as `state` or `geocode_settings` as removed | the database is the default `postgres` database of the `postgis/postgis` image, where the image also installed `postgis_tiger_geocoder` and `postgis_topology` (seen in `pg_extension`) | run against a database made with `CREATE DATABASE`: it starts empty and the first revision adds `postgis` |
| the app stops at startup with `seed init.roles failed: ... relation "SeedHistory" does not exist` | `DATABASE_URL` points at a database migrated before revision `0002_seed_history` (a developer's `.env` counts) | `uv run alembic upgrade head` against that database |
| `alembic upgrade head` prints no `Running upgrade` lines on a database you just created, and `psql` in the container shows no tables | another Postgres already listens on the same host port (a local install, another stack): a container published on `0.0.0.0:5432` starts without error, but `localhost:5432` goes to the other server, so migrations and seeds ran on **its** `poc` database | `lsof -nP -iTCP:5432 -sTCP:LISTEN` shows who holds the port; publish the container on a free port bound to loopback (`-p 127.0.0.1:5433:5432`) and set `DATABASE_URL` to that port; the same goes for Redis and `REDIS_PORT` |
| `uv sync` reports no interpreter satisfies `>=3.14` | no 3.14 installed and downloads are blocked | allow `uv python install 3.14`, or install 3.14 another way; do not lower the pin (rule T2) |

## Release
No release process exists: no staging or production, and nothing ships anywhere. Two workflows check pull requests (task 11.4, ADR-0032):
- `.github/workflows/agent-checks.yml` checks the PR body (the `### Verification` and `### Not verified` sections, a ticket ID) and silent check bypasses.
- `.github/workflows/ci.yml` runs three parallel jobs on every PR and on every push to `main`:
  | Job (check name) | Runs locally as | A red job means |
  |------------------|-----------------|-----------------|
  | `lint, types, contract, build` | `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run python -m app.cli --export-openapi --check`, `uv build` | the named step failed; a stale `openapi.json` is fixed by `uv run python -m app.cli --export-openapi` |
  | `unit and integration (real Postgres)` | `uv run pytest -m "not e2e"` (Docker) | a test failed; the log names it |
  | `e2e (processes, Redis, image builds)` | `uv run pytest tests/e2e` (Docker) | a process-level test failed, or an image no longer builds |

  CI installs with `uv sync --locked`, so a PR that changes the dependencies in `pyproject.toml` without regenerating `uv.lock` fails every job. It reads no secret and no `.env`. Making the three jobs required checks is a GitHub repository setting (an admin), not part of the repo.
