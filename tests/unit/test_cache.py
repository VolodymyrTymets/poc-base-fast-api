"""Cache serializer and key builder (task 9.1, ADR-0034). Ports the five cases of the Node `prisma.cache-transformer.spec.ts`."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.cache import MAX_PLAIN_INT, CacheDecodeError, deserialize, serialize

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
    ],
    ids=[
        "not-json",
        "empty",
        "no-value",
        "bad-base64",
        "bad-decimal",
        "bad-datetime",
        "bad-int",
    ],
)
def test_an_unreadable_entry_raises_cache_decode_error(text: str) -> None:
    # Act / Assert
    with pytest.raises(CacheDecodeError):
        deserialize(text)


@pytest.mark.parametrize(
    "value",
    [{1, 2}, {"id": uuid4()}, object(), {1: "a"}],
    ids=["set", "uuid", "object", "int-key"],
)
def test_a_value_that_cannot_be_cached_raises_type_error(value: object) -> None:
    # Act / Assert
    with pytest.raises(TypeError):
        serialize(value)


def test_a_nan_float_raises_value_error() -> None:
    # Act / Assert
    with pytest.raises(ValueError, match="not JSON compliant"):
        serialize({"x": float("nan")})


def test_a_dict_with_the_tag_key_raises_value_error() -> None:
    # Act / Assert
    with pytest.raises(ValueError, match="cacheType"):
        serialize({"$cacheType": "Date", "value": "x"})
