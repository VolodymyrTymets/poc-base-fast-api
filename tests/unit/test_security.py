import logging
import uuid
from datetime import timedelta
from typing import Any

import jwt
import pytest
from utils.clock import FROZEN_NOW
from utils.jwt import ACCESS_KEY, REFRESH_KEY

from app.config import Settings
from app.core.errors import UnauthorizedError
from app.core.security import (
    AuthConfigurationError,
    TokenType,
    issue_token,
    verify_token,
)

ACCOUNT_ID = str(uuid.UUID("11111111-1111-4111-8111-111111111111"))
SETTINGS = Settings(jwt_secret=ACCESS_KEY, jwt_refresh_token_secret=REFRESH_KEY)
ACCESS_VALUE = ACCESS_KEY.get_secret_value()
REFRESH_VALUE = REFRESH_KEY.get_secret_value()


def sign(payload: dict[str, Any], key: str = ACCESS_VALUE, alg: str = "HS256") -> str:
    return jwt.encode(payload, key, algorithm=alg)


def good_payload(**changes: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "sub": ACCOUNT_ID,
        "jti": "abc",
        "typ": "access",
        "iat": FROZEN_NOW,
        "exp": FROZEN_NOW + timedelta(minutes=15),
    }
    payload.update(changes)
    return {key: value for key, value in payload.items() if value is not None}


@pytest.mark.parametrize("token_type", list(TokenType))
def test_a_token_round_trips(token_type: TokenType, frozen_clock: Any) -> None:
    token = issue_token(SETTINGS, ACCOUNT_ID, token_type)

    claims = verify_token(SETTINGS, token, token_type)

    assert claims.account_id == ACCOUNT_ID
    assert claims.jti


def test_every_token_has_its_own_jti(frozen_clock: Any) -> None:
    first = issue_token(SETTINGS, ACCOUNT_ID, TokenType.REFRESH)
    second = issue_token(SETTINGS, ACCOUNT_ID, TokenType.REFRESH)

    assert first != second
    assert (
        verify_token(SETTINGS, first, TokenType.REFRESH).jti
        != verify_token(SETTINGS, second, TokenType.REFRESH).jti
    )


def test_the_payload_has_the_documented_claims_and_lifetimes(frozen_clock: Any) -> None:
    access = issue_token(SETTINGS, ACCOUNT_ID, TokenType.ACCESS)
    refresh = issue_token(SETTINGS, ACCOUNT_ID, TokenType.REFRESH)

    a = jwt.decode(access, ACCESS_VALUE, algorithms=["HS256"])
    r = jwt.decode(refresh, REFRESH_VALUE, algorithms=["HS256"])

    assert set(a) == {"sub", "jti", "typ", "iat", "exp"}
    assert (a["typ"], r["typ"]) == ("access", "refresh")
    assert a["exp"] - a["iat"] == 15 * 60
    assert r["exp"] - r["iat"] == 7 * 24 * 3600


def test_a_token_expires_exactly_at_its_lifetime(frozen_clock: Any) -> None:
    token = issue_token(SETTINGS, ACCOUNT_ID, TokenType.ACCESS)

    frozen_clock.shift(timedelta(minutes=15) - timedelta(seconds=1))
    assert verify_token(SETTINGS, token, TokenType.ACCESS).account_id == ACCOUNT_ID

    frozen_clock.shift(timedelta(seconds=1))
    with pytest.raises(UnauthorizedError):
        verify_token(SETTINGS, token, TokenType.ACCESS)


def test_a_tampered_signature_is_rejected(frozen_clock: Any) -> None:
    token = issue_token(SETTINGS, ACCOUNT_ID, TokenType.ACCESS)
    head, body, signature = token.split(".")
    flipped = ("A" if signature[0] != "A" else "B") + signature[1:]

    with pytest.raises(UnauthorizedError):
        verify_token(SETTINGS, f"{head}.{body}.{flipped}", TokenType.ACCESS)


def test_a_tampered_payload_is_rejected(frozen_clock: Any) -> None:
    forged = sign(good_payload(sub=str(uuid.uuid4())), key="another-key-" + "x" * 32)

    with pytest.raises(UnauthorizedError):
        verify_token(SETTINGS, forged, TokenType.ACCESS)


def test_an_unsigned_token_is_rejected(frozen_clock: Any) -> None:
    token = jwt.encode(good_payload(), None, algorithm="none")

    with pytest.raises(UnauthorizedError):
        verify_token(SETTINGS, token, TokenType.ACCESS)


def test_another_hmac_algorithm_is_rejected(frozen_clock: Any) -> None:
    token = sign(good_payload(), alg="HS384")

    with pytest.raises(UnauthorizedError):
        verify_token(SETTINGS, token, TokenType.ACCESS)


@pytest.mark.parametrize("missing", ["sub", "jti", "typ", "exp", "iat"])
def test_a_token_missing_a_claim_is_rejected(missing: str, frozen_clock: Any) -> None:
    token = sign(good_payload(**{missing: None}))

    with pytest.raises(UnauthorizedError):
        verify_token(SETTINGS, token, TokenType.ACCESS)


@pytest.mark.parametrize(
    "changes",
    [{"sub": "not-a-uuid"}, {"sub": 42}, {"jti": 7}, {"typ": "refresh"}, {"typ": 1}],
    ids=["sub-not-uuid", "sub-int", "jti-int", "wrong-typ", "typ-int"],
)
def test_a_token_with_a_bad_claim_value_is_rejected(
    changes: dict[str, Any], frozen_clock: Any
) -> None:
    token = sign(good_payload(**changes))

    with pytest.raises(UnauthorizedError):
        verify_token(SETTINGS, token, TokenType.ACCESS)


def test_the_right_typ_with_the_wrong_secret_is_rejected(frozen_clock: Any) -> None:
    refresh_signed_as_access = sign(good_payload(typ="access"), key=REFRESH_VALUE)

    with pytest.raises(UnauthorizedError):
        verify_token(SETTINGS, refresh_signed_as_access, TokenType.ACCESS)


def test_the_right_secret_with_the_wrong_typ_is_rejected(frozen_clock: Any) -> None:
    # Same secret on purpose: only the `typ` claim tells the two tokens apart here.
    same_secret = Settings(jwt_secret=ACCESS_KEY, jwt_refresh_token_secret=ACCESS_KEY)
    access = issue_token(same_secret, ACCOUNT_ID, TokenType.ACCESS)

    with pytest.raises(UnauthorizedError):
        verify_token(same_secret, access, TokenType.REFRESH)


def test_an_access_token_is_not_a_refresh_token_and_back(frozen_clock: Any) -> None:
    access = issue_token(SETTINGS, ACCOUNT_ID, TokenType.ACCESS)
    refresh = issue_token(SETTINGS, ACCOUNT_ID, TokenType.REFRESH)

    with pytest.raises(UnauthorizedError):
        verify_token(SETTINGS, access, TokenType.REFRESH)
    with pytest.raises(UnauthorizedError):
        verify_token(SETTINGS, refresh, TokenType.ACCESS)


@pytest.mark.parametrize("token", ["", "abc", "a.b.c", "....", " "])
def test_garbage_is_rejected(token: str) -> None:
    with pytest.raises(UnauthorizedError):
        verify_token(SETTINGS, token, TokenType.ACCESS)


def test_the_error_and_the_logs_carry_no_token(
    frozen_clock: Any, caplog: pytest.LogCaptureFixture
) -> None:
    token = sign(good_payload(), key="another-key-" + "x" * 32)

    with caplog.at_level(logging.DEBUG), pytest.raises(UnauthorizedError) as error:
        verify_token(SETTINGS, token, TokenType.ACCESS)

    assert token not in error.value.message
    assert error.value.details == []
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__
    assert token not in caplog.text


@pytest.mark.parametrize(
    ("token_type", "name"),
    [(TokenType.ACCESS, "JWT_SECRET"), (TokenType.REFRESH, "JWT_REFRESH_TOKEN_SECRET")],
)
def test_a_missing_secret_fails_loudly_and_names_the_setting(
    token_type: TokenType, name: str
) -> None:
    unset = Settings(jwt_secret=None, jwt_refresh_token_secret=None)

    with pytest.raises(AuthConfigurationError, match=name):
        issue_token(unset, ACCOUNT_ID, token_type)
    with pytest.raises(AuthConfigurationError, match=name):
        verify_token(unset, "a.b.c", token_type)
