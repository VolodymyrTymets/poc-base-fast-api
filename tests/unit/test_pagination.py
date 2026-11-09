import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from app.core.pagination import (
    DEFAULT_LIMIT,
    MAX_SEARCH_LENGTH,
    Page,
    PageParams,
    SearchText,
    like_pattern,
    page_params,
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
