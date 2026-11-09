# POC-9.1 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     Approved-by: <name> · <date> -->
Approved-by: Volodymyr · 2026-11-09 (approved in session, recorded by Claude at their instruction; Q1 answered by approving the stated default: keep and build the cache)

Pattern followed: `app/core/hashing.py` and `app/core/queue.py` (a `core` module with a narrow seam, stdlib or already-declared imports only, errors as small
exception classes, unit tests with no Docker); the behaviour is the Node `api/src/prisma/prisma.cache-transformer.ts` and its 5 specs, `prisma.caching.ts` for the TTLs and the `*` delimiter.
No precedent for a tagged JSON codec; the new pattern gets ADR-0034 (rule D1).

## Contract changes
- boundary: none (no route, `openapi.json` unchanged); new module `app/core/cache.py` with no importer yet.
- data: none. No Redis call, no new dependency, no new setting.
- generated output: none.

## Requirements (ordered; branch `feat/POC-9.1-cache-serializer`, one draft PR, one commit each)

### R1 — `serialize` / `deserialize` (M)
- files: `app/core/cache.py` (new: `CacheDecodeError`; `serialize` with a recursive encoder that tags `datetime` (isoformat, offset kept), `Decimal` (`str`), `bytes` (base64), big `int` (str); `deserialize` with `object_hook`, unknown tag raises `CacheDecodeError`; `json.dumps(..., allow_nan=False)` is not used because Decimal NaN is a tagged string, not a float; dict key `$cacheType` rejected)
- layer: core
- test: `tests/unit/test_cache.py` (new) — AC1 to AC5, one assertion subject each, AAA labels; the Node cases map 1:1 (Date, Decimal, bytes+bigint+plain, bytes type, unknown tag); plus the extra edge rows
- executed how: `uv run pytest tests/unit/test_cache.py`, and a one-off `uv run python -c` round trip of a record shaped like an `AccountProfile` row, output pasted in the PR
- risk: `json` converts a `datetime` subclass or an `int` subclass such as `bool` oddly; covered by the bool and boundary-int tests.

### R2 — `cache_key` and TTL constants (S)
- files: `app/core/cache.py` (change: `CACHE_TTL_SECONDS`, `CACHE_STALE_SECONDS`, `CACHE_KEY_PREFIX = "cache"`, `CACHE_KEY_DELIMITER = "*"`, `cache_key(model, args)` = `cache*<model>*sha256(canonical serialize(args, sorted keys))`)
- layer: core
- test: `tests/unit/test_cache.py` (change) — AC6, AC7; key stable under key order, differs by model and by args, a `datetime` argument hashes stably, `*` in a model raises
- executed how: `uv run pytest tests/unit/test_cache.py`; `uv run python -c "from app.core.cache import cache_key; print(cache_key('Account', {'id': 'x'}))"` output in the PR
- risk: canonical form must not depend on dict insertion order; tested by two orderings.

## Docs to update in this PR
- [ ] docs/features/POC-9.1/spec.md (acceptance criteria checked off)
- [ ] docs/decisions/ADR-0034-cache-serializer-and-keys.md (new, `proposed` until the human accepts it: Q1)
- [ ] docs/ARCHITECTURE.md — `app/core/` row lists `cache.py`; "Decided" bullet; "Planned" cache bullet says 9.1 is built and 9.2 is not
- [ ] docs/DOMAIN_GLOSSARY.md — terms "Cache key" and "Stale window"
- [ ] docs/BUSINESS_MODEL.md — status line (9.1 built, 9.2 and 9.3 not)
- [ ] `.claude/rules/project-structure.md` — only if it lists `core` modules (checked while implementing)

## Risks
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| Q1 answered "no cache" | the task and 9.2 are dropped | ask at approval, before any code |
| Tag collision with user data | a stored dict is read back as a value of another type | the `$cacheType` rejection test |
| Key hash covers args only | two services using one model name with different meaning share keys | the key includes the model; 9.2 decides what "args" are, and says so in its plan |

## Assumptions
- Q2 and Q3 of the spec; Q1 needs a human.
- The branch starts from `main` at `388be12` (8.3 merged). The untracked `Scope Breakdown ... .md`, `.serena/` and `dump.rdb` are not part of this PR.
- Python `int` is unbounded, so the big-int tag is for parity with the Node `BigInt` and for non-Python readers, not for a Python need.
