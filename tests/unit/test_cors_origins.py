import pytest

from app.config import DEFAULT_CORS_ORIGINS, parse_cors_origins


def test_falls_back_to_the_local_web_app_origins_when_unset() -> None:
    assert parse_cors_origins(None) == list(DEFAULT_CORS_ORIGINS)


@pytest.mark.parametrize("raw", ["", " , "], ids=["empty", "blank"])
def test_falls_back_to_the_defaults_for_an_empty_or_blank_value(raw: str) -> None:
    assert parse_cors_origins(raw) == list(DEFAULT_CORS_ORIGINS)


def test_splits_on_commas_and_trims_whitespace() -> None:
    raw = " http://localhost:4000 , https://app.example.com "

    assert parse_cors_origins(raw) == [
        "http://localhost:4000",
        "https://app.example.com",
    ]


def test_replaces_the_defaults_instead_of_extending_them() -> None:
    assert parse_cors_origins("http://localhost:4000") == ["http://localhost:4000"]
