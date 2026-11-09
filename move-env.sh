#!/bin/sh
# Copies this checkout's gitignored env files into another checkout (for example a new git worktree).
# Usage: ./move-env.sh [--force] <TARGET_DIR>
# Refuses to overwrite a file already in TARGET_DIR unless --force is given: it may hold that checkout's secrets.
set -eu

# Resolve the target before the cd below: a relative TARGET_DIR is relative to where the user ran this.

usage() {
  echo "Usage: ./move-env.sh [--force] <TARGET_DIR>" >&2
  echo "Copies .env, .env.development and .env.test (those that exist) into TARGET_DIR." >&2
  exit 1
}

force=0
if [ "${1:-}" = "--force" ]; then
  force=1
  shift
fi
[ $# -eq 1 ] || usage
target=$1
[ -d "$target" ] || { echo "not a directory: $target" >&2; usage; }
target=$(cd "$target" && pwd)
cd "$(dirname "$0")"
if [ "$target" = "$PWD" ]; then
  echo "target is this checkout: $target" >&2
  exit 1
fi

files=".env .env.development .env.test"

# Check everything before copying anything, so a refusal leaves the target untouched.
found=0
for f in $files; do
  [ -f "$f" ] || continue
  found=1
  if [ -e "$target/$f" ] && [ "$force" -eq 0 ]; then
    echo "refusing to overwrite $target/$f (use --force)" >&2
    exit 1
  fi
done
if [ "$found" -eq 0 ]; then
  echo "none of $files exists in $PWD: nothing to move" >&2
  exit 1
fi

for f in $files; do
  if [ -f "$f" ]; then
    cp "$f" "$target/$f"
    echo "copied $f"
  else
    echo "skipped $f (not found)"
  fi
done
