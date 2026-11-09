"""Cache serializer and key builder (task 9.1, ADR-0034). Ports the five cases of the Node `prisma.cache-transformer.spec.ts`."""

import re
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from enum import StrEnum
from fnmatch import fnmatchcase
from uuid import uuid4

import pytest

from app.core.cache import (
    CACHE_STALE_SECONDS,
    CACHE_TTL_SECONDS,
    MAX_PLAIN_INT,
    CacheDecodeError,
    cache_key,
    deserialize,
    invalidation_pattern,
    serialize,
)

PLUS_TWO = timezone(timedelta(hours=2))


def round_trip(value: object) -> object:
    return deserialize(serialize(value))


def test_an_aware_datetime_comes_back_equal() -> None:
    # Arrange
    at = datetime(2026, 10, 8, 10, 0, tzinfo=PLUS_TWO)

    # Act
    result = round_trip({"at": at})

    # Assert
    assert result == {"at": at}


def test_an_aware_datetime_keeps_its_offset() -> None:
    # Arrange
    at = datetime(2026, 10, 8, 10, 0, tzinfo=PLUS_TWO)

    # Act
    result = round_trip(at)

    # Assert
    assert isinstance(result, datetime)
    assert result.utcoffset() == timedelta(hours=2)


def test_a_utc_datetime_comes_back_equal() -> None:
    # Arrange
    at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    # Act
    result = round_trip(at)

    # Assert
    assert result == at


def test_a_naive_datetime_stays_naive() -> None:
    # Arrange
    at = datetime(
        2026, 10, 8, 10, 0
    )  # the column type is a naive UTC timestamp (ADR-0014)

    # Act
    result = round_trip(at)

    # Assert
    assert isinstance(result, datetime)
    assert result.tzinfo is None


@pytest.mark.parametrize("text", ["1234.56", "1E+3", "-0.00", "0.10"])
def test_a_decimal_comes_back_exact_with_its_exponent(text: str) -> None:
    # Arrange
    fee = Decimal(text)

    # Act
    result = round_trip(fee)

    # Assert
    assert isinstance(result, Decimal)
    assert str(result) == text


def test_a_decimal_nan_comes_back_as_a_decimal_nan() -> None:
    # Arrange
    fee = Decimal("NaN")

    # Act
    result = round_trip(fee)

    # Assert
    assert isinstance(result, Decimal)
    assert result.is_nan()


def test_bytes_come_back_as_bytes() -> None:
    # Arrange
    content = b"\x01\x02\x03"

    # Act
    result = round_trip({"content": content})

    # Assert
    assert result == {"content": content}
    assert isinstance(result, dict)
    assert isinstance(result["content"], bytes)


def test_big_ints_and_plain_values_come_back_equal() -> None:
    # Arrange
    value = {
        "content": b"\x01\x02\x03",
        "count": 2**63,
        "negative": -(2**63),
        "name": "Kestrel",
        "nested": [{"n": None, "ok": True}],
    }

    # Act
    result = round_trip(value)

    # Assert
    assert result == value


def test_a_bool_stays_a_json_boolean() -> None:
    # Act
    text = serialize({"ok": True})

    # Assert
    assert text == '{"ok":true}'


def test_an_int_at_the_plain_limit_is_written_plain() -> None:
    # Act
    text = serialize(MAX_PLAIN_INT)

    # Assert
    assert text == str(MAX_PLAIN_INT)


def test_an_int_one_beyond_the_plain_limit_is_written_as_a_tag() -> None:
    # Act
    text = serialize(MAX_PLAIN_INT + 1)

    # Assert
    assert text == f'{{"$cacheType":"BigInt","value":"{MAX_PLAIN_INT + 1}"}}'


def test_an_int_one_beyond_the_plain_limit_comes_back_equal() -> None:
    # Arrange
    value = MAX_PLAIN_INT + 1

    # Act
    result = round_trip(value)

    # Assert
    assert result == value


def test_a_tuple_comes_back_as_a_list() -> None:
    # Act
    result = round_trip({"ids": (1, 2)})

    # Assert
    assert result == {"ids": [1, 2]}


def test_an_unknown_tag_raises_and_names_it() -> None:
    # Act / Assert
    with pytest.raises(CacheDecodeError, match="Unknown"):
        deserialize('{"$cacheType":"Unknown","value":"x"}')


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "",
        '{"$cacheType":"Bytes"}',
        '{"$cacheType":"Bytes","value":"!!!"}',
        '{"$cacheType":"Decimal","value":"abc"}',
        '{"$cacheType":"DateTime","value":"yesterday"}',
        '{"$cacheType":"BigInt","value":"1.5"}',
        '{"$cacheType":"BigInt","value":" 1_0 "}',
        '{"$cacheType":"Bytes","value":"AA==","extra":1}',
    ],
    ids=[
        "not-json",
        "empty",
        "no-value",
        "bad-base64",
        "bad-decimal",
        "bad-datetime",
        "bad-int",
        "int-with-spaces",
        "extra-key",
    ],
)
def test_an_unreadable_entry_raises_cache_decode_error(text: str) -> None:
    # Act / Assert
    with pytest.raises(CacheDecodeError):
        deserialize(text)


class Role(StrEnum):
    ADMIN = "ADMIN"


@pytest.mark.parametrize(
    "value",
    [{1, 2}, {"id": uuid4()}, object(), {1: "a"}, {"role": Role.ADMIN}],
    ids=["set", "uuid", "object", "int-key", "str-enum"],
)
def test_a_value_that_cannot_be_cached_raises_type_error(value: object) -> None:
    # Act / Assert
    with pytest.raises(TypeError):
        serialize(value)


def test_a_nan_float_raises_value_error() -> None:
    # Act / Assert
    with pytest.raises(ValueError, match="not JSON compliant"):
        serialize({"x": float("nan")})


@pytest.mark.parametrize(
    "value",
    [{"$cacheType": "Date", "value": "x"}, [{"a": {"$cacheType": "Bytes"}}]],
    ids=["top-level", "nested"],
)
def test_a_dict_with_the_tag_key_raises_value_error(value: object) -> None:
    # Act / Assert
    with pytest.raises(ValueError, match="cacheType"):
        serialize(value)


def test_a_key_has_the_prefix_the_model_and_a_sha256_hex() -> None:
    # Act
    key = cache_key("Account", {"id": "a1"})

    # Assert
    assert re.fullmatch(r"cache\*Account\*[0-9a-f]{64}", key) is not None


def test_the_same_args_in_another_order_give_the_same_key() -> None:
    # Act
    first = cache_key("Account", {"where": {"id": "a1", "deleted": False}, "take": 1})
    second = cache_key("Account", {"take": 1, "where": {"deleted": False, "id": "a1"}})

    # Assert
    assert first == second


def test_other_args_give_another_key() -> None:
    # Act
    first = cache_key("Account", {"id": "a1"})
    second = cache_key("Account", {"id": "a2"})

    # Assert
    assert first != second


def test_another_model_gives_another_key() -> None:
    # Act
    first = cache_key("Account", {"id": "a1"})
    second = cache_key("AccountProfile", {"id": "a1"})

    # Assert
    assert first != second


def test_args_with_a_datetime_and_bytes_give_a_stable_key() -> None:
    # Arrange
    first_args = {"since": datetime(2026, 1, 1, tzinfo=UTC), "blob": b"\x01"}
    second_args = {"since": datetime(2026, 1, 1, tzinfo=UTC), "blob": bytes([1])}

    # Act
    first = cache_key("File", first_args)
    second = cache_key("File", second_args)

    # Assert
    assert first == second


@pytest.mark.parametrize(
    "model",
    ["", "Acc*ount", "Acc?ount", "Acc[ount", "Acc\\ount"],
    ids=["empty", "star", "question", "bracket", "backslash"],
)
def test_a_bad_model_name_raises_value_error(model: str) -> None:
    # Act / Assert
    with pytest.raises(ValueError, match="model name"):
        cache_key(model, {})


def as_fnmatch(pattern: str) -> str:
    # Redis writes a literal star as `\\*`, fnmatch as `[*]`.
    return pattern.replace("\\*", "[*]")


def test_the_invalidation_pattern_matches_the_keys_of_its_model() -> None:
    # Arrange
    key = cache_key("Account", {"id": "a1"})

    # Act
    matched = fnmatchcase(key, as_fnmatch(invalidation_pattern("Account")))

    # Assert
    assert matched is True


def test_the_invalidation_pattern_escapes_the_delimiters() -> None:
    # Act
    pattern = invalidation_pattern("Account")

    # Assert
    assert pattern == "cache\\*Account\\**"


def test_the_invalidation_pattern_does_not_match_a_longer_model_name() -> None:
    # Arrange
    other = cache_key("AccountProfile", {"id": "a1"})

    # Act
    matched = fnmatchcase(other, as_fnmatch(invalidation_pattern("Account")))

    # Assert
    assert matched is False


def test_the_ttl_is_60_seconds_and_the_stale_window_30() -> None:
    # Assert
    assert (CACHE_TTL_SECONDS, CACHE_STALE_SECONDS) == (60, 30)
