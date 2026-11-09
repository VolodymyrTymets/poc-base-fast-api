from typing import Annotated

import httpx
import pytest
import sqlalchemy as sa
from fastapi import Depends, FastAPI
from pydantic import BaseModel
from utils.client import running_client

from app.config import Settings
from app.core.pagination import (
    MAX_LIMIT,
    MAX_OFFSET,
    MAX_SEARCH_LENGTH,
    Page,
    PageParams,
    page_params,
    parse_sort,
)
from app.main import create_app

ROWS = [f"item-{n:02d}" for n in range(1, 26)]
TABLE = sa.table("Item", sa.column("name"))
ALLOWED = {"name": TABLE.c.name}


class Item(BaseModel):
    name: str


def build_app() -> FastAPI:
    app = create_app(Settings())

    @app.get("/api/v1/test-items", response_model=Page[Item])
    def list_items(params: Annotated[PageParams, Depends(page_params)]) -> Page[Item]:
        terms = parse_sort(params.sort, ALLOWED)
        names = [n for n in ROWS if params.search is None or params.search in n]
        for term in reversed(terms):
            names.sort(reverse=term.direction == "desc")
        page = names[params.offset : params.offset + params.limit]
        return Page[Item](items=[Item(name=n) for n in page], total=len(names))

    return app


async def get(query: str) -> httpx.Response:
    async with running_client(build_app()) as client:
        return await client.get(f"/api/v1/test-items?{query}")


async def test_defaults_give_the_first_twenty_rows_and_the_total() -> None:
    # Act
    response = await get("")

    # Assert
    body = response.json()
    assert (response.status_code, body["total"], len(body["items"])) == (200, 25, 20)


async def test_limit_offset_and_sort_slice_the_list() -> None:
    # Act
    response = await get("limit=3&offset=1&sort=name:desc")

    # Assert
    assert (response.status_code, response.json()) == (
        200,
        {
            "items": [{"name": "item-24"}, {"name": "item-23"}, {"name": "item-22"}],
            "total": 25,
        },
    )


async def test_an_offset_past_the_end_gives_no_items_and_the_real_total() -> None:
    # Act
    response = await get("offset=1000")

    # Assert
    assert (response.status_code, response.json()) == (200, {"items": [], "total": 25})


async def test_a_padded_search_is_trimmed_and_applied() -> None:
    # Act
    response = await get("search=%20item-07%20")

    # Assert
    assert (response.status_code, response.json()) == (
        200,
        {"items": [{"name": "item-07"}], "total": 1},
    )


@pytest.mark.parametrize(
    ("query", "field"),
    [
        (f"limit={MAX_LIMIT + 1}", "limit"),
        ("limit=0", "limit"),
        (f"offset={MAX_OFFSET + 1}", "offset"),
        ("offset=-1", "offset"),
        ("sort=secretcolumn", "sort"),
        ("sort=name:sideways", "sort"),
        ("search=" + "q" * (MAX_SEARCH_LENGTH + 1), "search"),
        ("search=a%00b", "search"),
    ],
)
async def test_a_bad_param_is_validation_failed_naming_the_field(
    query: str, field: str
) -> None:
    # Act
    response = await get(query)

    # Assert
    body = response.json()["error"]
    assert (response.status_code, body["code"]) == (422, "VALIDATION_FAILED")
    assert [(d["in"], d["field"]) for d in body["details"]] == [("query", field)]


@pytest.mark.parametrize(
    "query", ["sort=zqxsecret", "search=" + "zqx" * 40, "limit=zqxsecret"]
)
async def test_a_refused_value_is_not_in_the_response(query: str) -> None:
    # Act
    response = await get(query)

    # Assert
    assert (response.status_code, "zqx" in response.text) == (422, False)


def test_openapi_documents_the_page_envelope_and_the_query_params() -> None:
    # Arrange
    spec = build_app().openapi()

    # Act
    operation = spec["paths"]["/api/v1/test-items"]["get"]
    schema = next(
        s
        for name, s in spec["components"]["schemas"].items()
        if name.startswith("Page")
    )

    # Assert
    assert sorted(p["name"] for p in operation["parameters"]) == [
        "limit",
        "offset",
        "search",
        "sort",
    ]
    assert sorted(schema["properties"]) == ["items", "total"]
