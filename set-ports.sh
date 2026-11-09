#!/bin/sh
# Derives a non-colliding set of HOST-side ports from one base port and writes them into
# ./.env (gitignored), which docker compose reads for the ${EXPOSE_*} ports and a local,
# non-docker run reads for PORT, REDIS_PORT and DATABASE_URL. Container-internal ports
# (3001, 5432, 6379) are fixed in docker-compose.yml and never change.
# Usage: ./set-ports.sh <BASE_PORT>
set -eu

# Work relative to this script (the repo root), not the caller's directory: from a
# subdirectory this would otherwise write a stray .env there and still report success.
cd "$(dirname "$0")"

usage() {
  echo "Usage: ./set-ports.sh <BASE_PORT>" >&2
  echo "BASE_PORT must be a whole number, 1024-65530." >&2
  echo "Derives API_PORT (=BASE), POSTGRES_PORT (=BASE+1) and REDIS_PORT (=BASE+2): the" >&2
  echo "host-side ports of this stack. Writes them into ./.env." >&2
  exit 1
}

case "${1:-}" in
  '' | *[!0-9]*) usage ;;
esac
BASE_PORT=$1
if [ "$BASE_PORT" -lt 1024 ] || [ "$BASE_PORT" -gt 65530 ]; then
  usage
fi

API_PORT=$((BASE_PORT))
POSTGRES_PORT=$((BASE_PORT + 1))
REDIS_PORT=$((BASE_PORT + 2))

# Sets KEY=VALUE in FILE: replaces an existing KEY= line, appends otherwise. One awk pass,
# so a file whose last line has no trailing newline does not get the key glued onto it.
set_kv() {
  file="$1"
  key="$2"
  value="$3"
  touch "$file"
  awk -v k="$key" -v v="$value" '
    BEGIN { FS = OFS = "=" }
    $1 == k { $0 = k "=" v; found = 1 }
    { print }
    END { if (!found) print k "=" v }
  ' "$file" > "$file.tmp" && mv "$file.tmp" "$file"
}

# Rewrites only the :<port>/ part of an existing KEY=scheme://...@host:port/... line.
# Does nothing when the file or the key is missing: it overrides a value, never invents one.
set_url_port() {
  file="$1"
  key="$2"
  port="$3"
  [ -f "$file" ] || return 0
  grep -q "^${key}=.*://" "$file" 2>/dev/null || return 0
  if ! grep -qE "^${key}=.*://[^/]*:[0-9]+/" "$file"; then
    echo "warning: $key in $file has no :port/ to rewrite; a local run still uses its old port" >&2
    return 0
  fi
  sed -E -i.bak "s|(^${key}=.*://[^/]*:)[0-9]+(/.*)|\\1${port}\\2|" "$file"
  rm -f "$file.bak"
}

echo "Deriving ports from base $BASE_PORT:"
echo "  API_PORT=$API_PORT"
echo "  POSTGRES_PORT=$POSTGRES_PORT"
echo "  REDIS_PORT=$REDIS_PORT"

echo "Writing $PWD/.env..."
# EXPOSE_* (compose's published host ports) are named apart from PORT and REDIS_PORT (the
# API process's own settings): a shell that exports REDIS_PORT cannot then override compose.
set_kv "$PWD/.env" EXPOSE_API_PORT "$API_PORT"
set_kv "$PWD/.env" EXPOSE_POSTGRES_PORT "$POSTGRES_PORT"
set_kv "$PWD/.env" EXPOSE_REDIS_PORT "$REDIS_PORT"
# A local run dials Postgres and Redis on their published host ports, which just changed;
# without this a second checkout would keep using the first one's database and queue.
set_kv "$PWD/.env" PORT "$API_PORT"
set_kv "$PWD/.env" REDIS_PORT "$REDIS_PORT"
set_url_port "$PWD/.env" DATABASE_URL "$POSTGRES_PORT"

echo "Done."
