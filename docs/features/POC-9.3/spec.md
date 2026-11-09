# POC-9.3 — list helpers

## Problem
No route lists records yet, and the next POC built on this base will add several. Without a shared helper each list route would invent its own
`limit`/`offset` names, its own sort syntax and its own response shape, and a free-text `sort` value would reach `ORDER BY` unchecked.

## Goal / business value
Goal 1 (scaffolding: a fork gets one obvious way to write a list endpoint) and goal 2 (no unchecked client input in a query). Scope doc task 9.3.
Package 9 has no dependency on 9.1 or 9.2 (both rejected), so this task stands alone.

## Scope
- in: `app/core/pagination.py`: the query params `limit`, `offset`, `sort`, `search` as one `Depends` (`page_params`); the `Page[T]` envelope `{items, total}`;
  a sort allow-list (`parse_sort`) that maps public field names to columns and refuses any other name; `apply_page` to put sort, limit and offset on a `select`;
  `like_pattern` to turn a search string into an escaped `ILIKE` pattern.
- **out (explicit):** any route, schema or service that lists something (no new domain endpoint, rule P3); running the count query (the caller's service does,
  so no database test here); cursor pagination; filters other than `search`; a new error code (ADR-0003); a new dependency (C2).

## Acceptance criteria
- [x] AC1 `limit` defaults to 20, accepts 1 to 100, `offset` defaults to 0 and is 0 to 2**31 - 1; a value outside gives 422 `VALIDATION_FAILED` naming the field.
- [x] AC2 `sort=name:desc,createdAt` parses to ordered terms (direction defaults to `asc`); a field not in the allow-list, a bad direction, a repeated field, or
  more than 3 terms gives 422 `VALIDATION_FAILED` with `details` naming `sort`, and the message does not echo the submitted text.
- [x] AC3 `apply_page` yields `ORDER BY` from the terms only through the allow-list's columns (compiled SQL checked), then `LIMIT` and `OFFSET`; with no `sort` it uses the
  caller's default order, so paging is stable.
- [x] AC4 `search` is trimmed, blank means none, max 100 characters, no control characters; `like_pattern` escapes `%`, `_` and `\` so they match literally.
- [x] AC5 `Page[T]` serialises as `{"items": [...], "total": n}` and appears in OpenAPI for a test-local route; `items` carries the caller's response model, never an ORM object.
- [x] AC6 `openapi.json` is unchanged (no real route is added); ruff, mypy, unit and integration tests green.

## Edge cases
| Case | Expected behaviour | Decided by |
|------|--------------------|-----------|
| `offset` beyond `total` | 200 with `items: []` and the real `total` | assumption A3 |
| `sort` empty string | treated as not sent | assumption A2 |
| `sort=name:DESC` | refused: directions are lowercase `asc` / `desc` | assumption A2 |
| search contains `%` | matches a literal percent sign | AC4 |
| a column under two allow-list names | the allow-list maps name to column; two names for one column is the caller's choice | A4 |

## Open questions
| # | Question | My assumed answer | Needs a human? |
|---|----------|-------------------|----------------|
| A1 | Defaults and caps | `limit` 20, max 100; `offset` 0 to 2**31 - 1 (a larger value is a 422, not a database error) | no |
| A2 | Sort syntax | `field:dir` joined by commas, max 3 terms; direction optional (`asc`); names are the camelCase API names | no |
| A3 | Is `total` computed here? | No: the service runs `select count()` over the same filtered query; `Page` is only the envelope | no |
| A4 | Allow-list shape | `Mapping[str, ColumnElement[Any]]`, the key is the public name; `Any` is SQLAlchemy's own type parameter, so no `# type: ignore` | no |
| A5 | "Backend rule 18" the scope doc cites | Not in this repo's `.claude/rules`; the allow-list rule is what this task states | no |
