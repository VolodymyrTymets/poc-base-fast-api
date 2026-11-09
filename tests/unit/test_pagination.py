import pytest
import sqlalchemy as sa
from pydantic import BaseModel, TypeAdapter, ValidationError

from app.core.errors import ValidationFailedError
from app.core.pagination import (
    DEFAULT_LIMIT,
    MAX_SEARCH_LENGTH,
    Page,
    PageParams,
    SearchText,
    SortTerm,
    apply_page,
    like_pattern,
    page_params,
    parse_sort,
)

SEARCH = TypeAdapter(SearchText)


class Item(BaseModel):
    name: str


def test_params_default_when_nothing_is_sent() -> None:
    # Act
    params = page_params()

    # Assert
    assert params == PageParams(limit=DEFAULT_LIMIT, offset=0, sort=None, search=None)


def test_an_empty_sort_counts_as_not_sent() -> None:
    # Act
    params = page_params(sort="")

    # Assert
    assert params.sort is None


def test_a_search_is_trimmed() -> None:
    # Act
    result = SEARCH.validate_python("  anna ")

    # Assert
    assert result == "anna"


def test_a_blank_search_counts_as_not_sent() -> None:
    # Act
    result = SEARCH.validate_python("   ")

    # Assert
    assert result is None


def test_a_search_at_the_length_limit_is_accepted() -> None:
    # Arrange
    value = "a" * MAX_SEARCH_LENGTH

    # Act
    result = SEARCH.validate_python(value)

    # Assert
    assert result == value


def test_a_search_over_the_length_limit_is_refused_without_echoing_it() -> None:
    # Arrange
    submitted = "zq" * (MAX_SEARCH_LENGTH // 2 + 1)

    # Act
    with pytest.raises(ValidationError) as info:
        SEARCH.validate_python(submitted)

    # Assert
    assert [e["type"] for e in info.value.errors()] == ["string_too_long"]
    assert "zqzqzq" not in info.value.errors()[0]["msg"]


@pytest.mark.parametrize(
    "value", ["a\x00b", "a\tb", "\na"], ids=["nul", "tab", "newline"]
)
def test_a_search_with_a_control_character_is_refused(value: str) -> None:
    # Act
    with pytest.raises(ValidationError) as info:
        SEARCH.validate_python(value)

    # Assert
    assert [e["type"] for e in info.value.errors()] == ["control_character"]


def test_page_serialises_as_items_and_total() -> None:
    # Act
    page = Page[Item](items=[Item(name="a")], total=7)

    # Assert
    assert page.model_dump() == {"items": [{"name": "a"}], "total": 7}


def test_page_refuses_a_negative_total() -> None:
    # Act
    with pytest.raises(ValidationError) as info:
        Page[Item](items=[], total=-1)

    # Assert
    assert [e["loc"] for e in info.value.errors()] == [("total",)]


def test_page_schema_names_both_fields_and_the_item_model() -> None:
    # Act
    schema = Page[Item].model_json_schema()

    # Assert
    assert sorted(schema["properties"]) == ["items", "total"]
    assert "Item" in schema["$defs"]


@pytest.mark.parametrize(
    ("search", "pattern"),
    [
        ("anna", "%anna%"),
        ("50%", "%50\\%%"),
        ("a_b", "%a\\_b%"),
        ("a\\b", "%a\\\\b%"),
        ("%_\\", "%\\%\\_\\\\%"),
    ],
)
def test_like_pattern_matches_wildcards_literally(search: str, pattern: str) -> None:
    # Act
    result = like_pattern(search)

    # Assert
    assert result == pattern


ITEMS = sa.table("Item", sa.column("name"), sa.column("createdAt"), sa.column("id"))
ALLOWED = {"name": ITEMS.c.name, "createdAt": ITEMS.c.createdAt}


def sql(params: PageParams) -> str:
    stmt = apply_page(sa.select(ITEMS.c.id), params, ALLOWED, [ITEMS.c.id])
    return str(stmt.compile())


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, []),
        ("", []),
        ("name", [SortTerm("name", "asc")]),
        ("name:desc", [SortTerm("name", "desc")]),
        (
            "name:asc,createdAt:desc",
            [SortTerm("name", "asc"), SortTerm("createdAt", "desc")],
        ),
    ],
)
def test_parse_sort_accepts(raw: str | None, expected: list[SortTerm]) -> None:
    # Act
    terms = parse_sort(raw, ALLOWED)

    # Assert
    assert terms == expected


@pytest.mark.parametrize(
    "raw",
    [
        "password",
        "name:up",
        "name:DESC",
        "name:",
        ":asc",
        "name,name:desc",
        "name,createdAt,name,createdAt",
        "name;select 1",
        "name:asc:desc",
    ],
)
def test_parse_sort_refuses_with_a_sort_invalid_detail(raw: str) -> None:
    # Act
    with pytest.raises(ValidationFailedError) as info:
        parse_sort(raw, ALLOWED)

    # Assert
    detail = info.value.details[0]
    assert isinstance(detail, dict)
    assert (info.value.status_code, detail["field"], detail["type"]) == (
        422,
        "sort",
        "sort_invalid",
    )
    assert "createdAt, name" in detail["message"]


@pytest.mark.parametrize("raw", ["zqxsecret", "zqxsecret:desc", "name:zqxsecret"])
def test_parse_sort_never_echoes_the_submitted_text(raw: str) -> None:
    # Act
    with pytest.raises(ValidationFailedError) as info:
        parse_sort(raw, ALLOWED)

    # Assert
    assert "zqxsecret" not in str(info.value.body())


def test_apply_page_orders_by_the_allowed_column_then_the_default() -> None:
    # Act
    text = sql(PageParams(limit=5, offset=10, sort="name:desc", search=None))

    # Assert
    assert 'ORDER BY "Item".name DESC, "Item".id' in text
    assert "LIMIT :param_1 OFFSET :param_2" in text


def test_apply_page_without_a_sort_uses_the_default_order() -> None:
    # Act
    text = sql(PageParams(limit=5, offset=0, sort=None, search=None))

    # Assert
    assert 'ORDER BY "Item".id' in text
    assert "name" not in text.split("ORDER BY")[1]


def test_apply_page_carries_limit_and_offset_as_parameters() -> None:
    # Arrange
    stmt = apply_page(
        sa.select(ITEMS.c.id),
        PageParams(limit=7, offset=21, sort=None, search=None),
        ALLOWED,
        [ITEMS.c.id],
    )

    # Act
    values = stmt.compile().params

    # Assert
    assert sorted(values.values()) == [7, 21]
