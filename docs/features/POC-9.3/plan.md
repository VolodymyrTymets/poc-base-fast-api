# POC-9.3 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     Approved-by: <name> · <date> -->
Approved-by: Volodymyr · 2026-11-09

Pattern followed: `app/core/validation.py` (one `core` module per concern, imports no layer, fixed messages that never echo input) and `app/core/errors.py`
(`ValidationFailedError` with `details` entries `{field, in, message, type}`, the shape `validation_details` builds). Tests follow `tests/unit/test_validation.py` (pure)
and the test-local-route style of POC-4.3's HTTP test, run through `running_client(create_app(Settings()))`, no database. No precedent for a query-param dependency
exists; it stays inside ADR-0003 and ADR-0011 (pagination is named in `core/`), so no ADR.
Layer: `core` only.

## Contract changes
- boundary: none live. No route is added, so `openapi.json` must not change. The envelope and params become the convention for future list routes.
- data: none.
- generated output: none expected; `--export-openapi --check` proves it.

## Requirements (ordered; branch `feat/POC-9.3-list-helpers`, one draft PR, one commit each)

### R1 — Params, envelope and search (M)
- files: `app/core/pagination.py` (new): constants `DEFAULT_LIMIT=20`, `MAX_LIMIT=100`, `MAX_SEARCH_LENGTH=100`; frozen dataclass `PageParams(limit, offset, sort, search)`;
  `page_params(...)` using `Query(ge=, le=)` for `limit` and `offset`, `sort` and `search` as optional strings; `Page[T](BaseModel)` generic with `items: list[T]`, `total: int`
  (`ge=0`); `like_pattern(search) -> str`. `offset` is `ge=0, le=MAX_OFFSET` (`MAX_OFFSET = 2**31 - 1`, so a huge value is a 422, not a database 500).
  `search` is `Annotated[str | None, Query(max_length=100), AfterValidator(_search)]`, so FastAPI's own validation produces the 422: `_search` trims, maps blank to `None`, and
  raises `PydanticCustomError("control_character", ...)` with a fixed message (the mechanism of `app/core/validation.py`, a 3-line local check, no refactor of 4.3, rule C1).
  Nothing is raised from inside the dependency body, so no 500 path.
- layer: core.
- test: `tests/unit/test_pagination.py`: defaults; bounds 0/1/100/101 for `limit` and -1/0 for `offset`; `Page[Item]` dump and `model_json_schema`; `like_pattern` escapes `%`, `_` and a backslash;
  blank and 101-character search.
- executed how: `uv run python -c` building `page_params` results and a `Page`, printing the dump and the pattern; the HTTP call is R3.
- risk: FastAPI's `Query` bound errors may carry the submitted value; confirm in the R3 test that the 422 body holds no submitted text.

### R2 — Sort allow-list and `apply_page` (M)
- files: `app/core/pagination.py` (change): `SortTerm(field, direction)`, `parse_sort(raw, allowed) -> list[SortTerm]`, `apply_page(stmt, params, allowed, default_order)`.
  `parse_sort` raises `ValidationFailedError` with one detail `{"field": "sort", "in": "query", "message": <fixed text naming the allowed fields>, "type": "sort_invalid"}`;
  the allowed names are ours, never the submitted text. `apply_page` is typed in the repo's SQLAlchemy 2.1 style, a variadic generic: `def apply_page[*Ts](stmt: Select[*Ts], params: PageParams, allowed: Mapping[str, ColumnElement[Any]], default_order: Sequence[ColumnElement[Any]]) -> Select[*Ts]`
  (precedent: `Select[Account]` in `app/services/account.py:76`; `Select[tuple[X]]` is the 2.0 form and wrong here). `Any` only as SQLAlchemy's own type parameter (rule D3).
- layer: core.
- test: extend `tests/unit/test_pagination.py`: accepted forms (`name`, `name:desc`, `name:asc,createdAt:desc`); refusals (unknown field, `name:up`, `name:DESC`, duplicate field,
  4 terms, `name:`, `:asc`, a value that is an SQL fragment); the error body never contains the submitted string; compiled SQL of `apply_page` on a small in-test SQLAlchemy table
  has `ORDER BY` of the allowed columns only, `LIMIT`, `OFFSET`, and the default order when `sort` is absent.
- executed how: `uv run python -c` printing the compiled PostgreSQL SQL for two requests.
- risk: SQLAlchemy 2 `Select` generics under mypy strict; cheapest check is `uv run mypy` right after the signature is written, before the tests.

### R3 — HTTP check and docs (S)
- files: `tests/integration/http/test_http_pagination.py` (new, no database, `running_client(create_app(Settings()))` with a test-local `GET /items` route returning `Page[Item]` from an in-memory list
  through `parse_sort`); `docs/api/ENDPOINTS.md` ("List conventions" section), `docs/api/ERRORS.md` (the `sort_invalid` type), `docs/ARCHITECTURE.md`.
- test: 200 envelope with `total` equal to the list size and a page slice; `limit=101`, `offset` over `MAX_OFFSET`, an unlisted sort field, a 101-character `search` and a `search` with a control character each give 422 `VALIDATION_FAILED` with the field in `details` and the submitted text absent from the body; `offset` past the end gives `items: []`; a padded `search` is trimmed and accepted; `app.openapi()["components"]["schemas"]` holds the `Page[Item]` schema with `items` and `total` (AC5).
- executed how (evidence): a scratchpad script serving that route with `uvicorn`, then `curl -i` for a good page, a trimmed search, a bad sort, a bad limit and a bad search; paste the responses.
- risk: none beyond R1 and R2.

## Done check (rule B1)
Run and paste: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest tests/unit`, `uv run pytest -m "not db and not redis"`,
`uv run python -m app.cli --export-openapi --check`. A full `uv run pytest -m "not e2e"` needs Docker; if it cannot run it goes under "Not verified".

## Docs (same PR, rule E1)
- [ ] docs/features/POC-9.3/spec.md (criteria checked off)
- [ ] docs/api/ENDPOINTS.md (query params, envelope, sort syntax)
- [ ] docs/api/ERRORS.md (`sort_invalid` as a `details` type under `VALIDATION_FAILED`; no new code)
- [ ] docs/ARCHITECTURE.md (`pagination.py` built in `app/core/`; the "Planned" cache and list-helpers bullet narrows to the cache)
- [ ] docs/DOMAIN_GLOSSARY.md: none (no new domain term). ADR: none. `BUSINESS_MODEL.md` status line only if it names 9.3.

## Risks and unknowns
| Risk | Impact | Cheapest way to find out early |
|------|--------|-------------------------------|
| A sort value reaches SQL | injection | R2 compiled-SQL test with hostile input; columns come only from the allow-list |
| `Query` bound errors echo the value | leak in a 422 | R3 test asserts the body lacks the submitted text |
| Generic `Page[T]` OpenAPI naming (`Page_Item_`) | ugly schema names for future routes | check the schema name in the R1 test, accept FastAPI's default |

## Before R1
`main` carries unrelated changes (`.env.example`, `.env.development.example`, untracked `.serena/`, `dump.rdb`, the scope-doc copy). Branch from it, then stage files by path only; never `git add -A`, and `dump.rdb` is never committed (protected-paths).

## Assumptions
A1 to A5 of the spec. The scope doc marks 9.1 and 9.2 Rejected (and 9.1 was reverted in `7cc1f2e`); 9.3 does not depend on them.

## Estimate
R1 M, R2 M, R3 S.

## Not covered
Any real list route, the count query, filters beyond `search`, cursors, the rejected cache (9.1, 9.2).
