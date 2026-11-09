"""List helpers for future list routes: paging params, the `{items, total}` envelope, search. Tasks: 9.3 (ADR-0003).

A list route takes `Depends(page_params)` and returns `Page[ItemResponse]`. The service runs the query and the count
(this module only shapes them), so nothing here touches a database. Every value is checked by FastAPI's own request
validation, so a bad one is the usual 422 `VALIDATION_FAILED` and a message never holds the submitted text (rules D8, P4).
"""

import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from fastapi import Query
from pydantic import AfterValidator, BaseModel, Field
from pydantic_core import PydanticCustomError
from sqlalchemy import ColumnElement, Select

from app.core.errors import ValidationFailedError

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
# The largest int32: a bigger OFFSET is a 422 here instead of a database error (a 500) in the service.
MAX_OFFSET = 2**31 - 1
MAX_SEARCH_LENGTH = 100
# A generous cap on the raw `sort` text; the number of terms is checked when it is parsed.
MAX_SORT_LENGTH = 200
MAX_SORT_TERMS = 3


class Page[T](BaseModel):
    """The body of a list response. `items` holds the route's response model, never an ORM object (rule 2 of `api-rest.md`)."""

    items: list[T]
    total: int = Field(
        ge=0, description="Rows matching the request before limit and offset"
    )


@dataclass(frozen=True)
class PageParams:
    limit: int
    offset: int
    sort: str | None
    search: str | None


def _search(value: str | None) -> str | None:
    if value is None:
        return None
    # Checked before the trim: a tab or newline at the edge is still a control character.
    if any(unicodedata.category(char) == "Cc" for char in value):
        raise PydanticCustomError(
            "control_character", "Must not contain control characters"
        )
    return value.strip() or None


# Public so a unit test can validate it without an app.
SearchText = Annotated[
    str | None, Query(max_length=MAX_SEARCH_LENGTH), AfterValidator(_search)
]


def page_params(
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0, le=MAX_OFFSET)] = 0,
    sort: Annotated[str | None, Query(max_length=MAX_SORT_LENGTH)] = None,
    search: SearchText = None,
) -> PageParams:
    """The paging query params of a list route. `sort` is raw text here: `parse_sort` checks it against the route's allow-list."""
    return PageParams(limit=limit, offset=offset, sort=sort or None, search=search)


def like_pattern(search: str) -> str:
    """A contains-pattern for `column.ilike(pattern, escape="\\\\")`, with `%`, `_` and the backslash matched literally."""
    escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@dataclass(frozen=True)
class SortTerm:
    field: str
    direction: Literal["asc", "desc"]


def _bad_sort(allowed: Mapping[str, ColumnElement[Any]]) -> ValidationFailedError:
    # The message lists our own field names and never the submitted text (rules D8, P4).
    names = ", ".join(sorted(allowed))
    return ValidationFailedError(
        details=[
            {
                "in": "query",
                "field": "sort",
                "message": (
                    f"Use field or field:asc or field:desc, comma separated, "
                    f"at most {MAX_SORT_TERMS} different fields from: {names}"
                ),
                "type": "sort_invalid",
            }
        ]
    )


def parse_sort(
    raw: str | None, allowed: Mapping[str, ColumnElement[Any]]
) -> list[SortTerm]:
    """`name:desc,createdAt` as ordered terms; any field outside `allowed`, a bad direction, a repeat or too many terms is a 422.

    `allowed` maps the API field name to the column, so a client value never reaches `ORDER BY` as text.
    """
    if not raw:
        return []
    parts = raw.split(",")
    if len(parts) > MAX_SORT_TERMS:
        raise _bad_sort(allowed)
    terms: list[SortTerm] = []
    for part in parts:
        field, colon, direction = part.partition(":")
        if not colon:
            direction = "asc"
        if field not in allowed or any(term.field == field for term in terms):
            raise _bad_sort(allowed)
        if direction == "asc":
            terms.append(SortTerm(field, "asc"))
        elif direction == "desc":
            terms.append(SortTerm(field, "desc"))
        else:
            raise _bad_sort(allowed)
    return terms


def apply_page[*Ts](
    stmt: Select[*Ts],
    params: PageParams,
    allowed: Mapping[str, ColumnElement[Any]],
    default_order: Sequence[ColumnElement[Any]],
) -> Select[*Ts]:
    """Order, limit and offset `stmt`. `default_order` always follows the requested sort, so equal rows never swap between pages."""
    order = [
        allowed[term.field].asc()
        if term.direction == "asc"
        else allowed[term.field].desc()
        for term in parse_sort(params.sort, allowed)
    ]
    return (
        stmt.order_by(*order, *default_order).limit(params.limit).offset(params.offset)
    )
