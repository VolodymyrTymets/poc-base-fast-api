#!/bin/sh
# Container entrypoint (task 11.1, ADR-0030): wait for Postgres, then migrate and seed, then run the command.
# RUN_MIGRATIONS=0 (the worker image) skips the migrate and seed steps, so only the API container owns the schema.
# `set -e` makes a failing wait, migration or seed stop the container with its status (rule D5); `exec` makes the
# command PID 1, so `docker stop` delivers SIGTERM to it and the graceful shutdown runs.
set -eu

: "${DATABASE_URL:?DATABASE_URL is not set}"

python scripts/wait_for_postgres.py

if [ "${RUN_MIGRATIONS:-1}" != "0" ]; then
    alembic upgrade head
    python -m app.seeds
fi

exec "$@"
