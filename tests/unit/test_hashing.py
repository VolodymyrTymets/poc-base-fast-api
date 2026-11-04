"""Argon2id hashing seam (task 7.1, ADR-0028)."""

import logging

import pytest

from app.core.hashing import (
    ARGON2_MEMORY_COST_KIB,
    ARGON2_PARALLELISM,
    ARGON2_TIME_COST,
    hash_secret,
    hash_token,
    token_matches,
    verify_secret,
)

CODE = "123456"  # a fake sign-in code
OTHER_CODE = "654321"


async def test_a_hash_verifies_against_its_secret() -> None:
    hashed = await hash_secret(CODE)

    assert await verify_secret(CODE, hashed) is True


async def test_a_wrong_secret_does_not_verify() -> None:
    hashed = await hash_secret(CODE)

    assert await verify_secret(OTHER_CODE, hashed) is False


async def test_an_empty_secret_does_not_verify() -> None:
    hashed = await hash_secret(CODE)

    assert await verify_secret("", hashed) is False


async def test_the_hash_of_another_secret_does_not_verify() -> None:
    foreign = await hash_secret(OTHER_CODE)

    assert await verify_secret(CODE, foreign) is False


async def test_two_hashes_of_one_secret_differ() -> None:
    first = await hash_secret(CODE)
    second = await hash_secret(CODE)

    assert first != second


async def test_the_hash_is_argon2id_with_the_chosen_cost_and_holds_no_secret() -> None:
    hashed = await hash_secret(CODE)

    prefix = (
        f"$argon2id$v=19$m={ARGON2_MEMORY_COST_KIB},"
        f"t={ARGON2_TIME_COST},p={ARGON2_PARALLELISM}$"
    )
    assert (hashed.startswith(prefix), CODE in hashed) == (True, False)


@pytest.mark.parametrize(
    "not_a_hash",
    ["", "plain-text", "$2b$10$abcdefghijklmnopqrstuuabcdefghijklmnopqrstuvwxyz01234"],
    ids=["empty", "plain", "bcrypt"],
)
async def test_a_string_that_is_not_an_argon2_hash_verifies_false_and_is_logged_without_it(
    not_a_hash: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="app.core.hashing"):
        result = await verify_secret(CODE, not_a_hash)

    assert (result, [r.getMessage() for r in caplog.records]) == (
        False,
        ["a stored hash is not in a readable format"],
    )


def test_hash_token_is_the_known_sha256_hex() -> None:
    # sha256("abc"), from FIPS 180-2.
    assert (
        hash_token("abc")
        == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_a_token_matches_its_own_hash_only() -> None:
    stored = hash_token("token-one")

    assert token_matches("token-one", stored) is True
    assert token_matches("token-two", stored) is False


def test_a_missing_stored_hash_never_matches() -> None:
    assert token_matches("token-one", None) is False


def test_a_stored_token_hash_is_not_an_argon2_string() -> None:
    stored = hash_token("token-one")

    assert len(stored) == 64
    assert not stored.startswith("$argon2")
