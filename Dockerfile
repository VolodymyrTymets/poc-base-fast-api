# Container image for the API and the worker (task 11.1, ADR-0030). Build a target:
#   docker build --target development -t poc-api .
#   docker build --target worker -t poc-worker .
# `development` migrates and seeds, then serves; `worker` waits for Postgres and runs the arq worker.

FROM python:3.14-slim AS base

# Pinned to the uv the lockfile was made with; `uv sync --locked` fails if uv.lock is stale.
COPY --from=ghcr.io/astral-sh/uv:0.12.22 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH=/app/.venv/bin:$PATH \
    HOST=0.0.0.0

# A non-root user owns the app and the virtualenv.
RUN useradd --system --create-home --shell /usr/sbin/nologin app \
    && mkdir /app \
    && chown app:app /app
USER app
WORKDIR /app

# Dependencies first, so a source change does not reinstall them.
COPY --chown=app:app pyproject.toml uv.lock .python-version README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY --chown=app:app app ./app
COPY --chown=app:app migrations ./migrations
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app scripts ./scripts
COPY --chown=app:app docker-entrypoint.sh ./
RUN uv sync --locked --no-dev

ENTRYPOINT ["./docker-entrypoint.sh"]


FROM base AS development
# Adds the dev group and the tests, so the suite can run inside the container.
RUN uv sync --locked
COPY --chown=app:app tests ./tests
COPY --chown=app:app openapi.json ./
CMD ["poc-base-fast-api"]


FROM base AS worker
# The API container owns the schema and the seeds; a worker never migrates, so two containers never race.
ENV RUN_MIGRATIONS=0
CMD ["arq", "app.worker.WorkerSettings"]
