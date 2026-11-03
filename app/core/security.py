"""The JWT codec: issue and verify the access and the refresh token. Tasks: 4.4 (ADR-0008, ADR-0010).

HS256 only, payload `{sub, jti, typ, iat, exp}`. Each token type has its own secret and its own
`typ`, so an access token is never valid as a refresh token or the reverse. The codec checks the
signature and the claims; whether the account still exists, or the refresh token matches the stored
sha256, is the job of the services (tasks 5.3, 7.4).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

import jwt
from pydantic import SecretStr

from app.config import Settings
from app.core.errors import UnauthorizedError

ALGORITHM = "HS256"
_REQUIRED_CLAIMS = ["exp", "iat", "sub", "jti", "typ"]


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


class AuthConfigurationError(RuntimeError):
    """A token secret is not set. A deploy mistake, so it is a 500 and not an `AppError`."""


@dataclass(frozen=True, slots=True)
class TokenClaims:
    """What a verified token says: the account it was issued to and the token's own id."""

    account_id: str
    jti: str


def _secret_for(settings: Settings, token_type: TokenType) -> str:
    secret: SecretStr | None
    if token_type is TokenType.ACCESS:
        secret, name = settings.jwt_secret, "JWT_SECRET"
    else:
        secret, name = settings.jwt_refresh_token_secret, "JWT_REFRESH_TOKEN_SECRET"
    # Never fall back to a default key: an unset secret must not sign or verify anything.
    if secret is None or not secret.get_secret_value():
        raise AuthConfigurationError(f"{name} is not set")
    return secret.get_secret_value()


def _lifetime(settings: Settings, token_type: TokenType) -> timedelta:
    if token_type is TokenType.ACCESS:
        return settings.jwt_access_token_expires_in
    return settings.jwt_refresh_token_expires_in


def issue_token(settings: Settings, account_id: str, token_type: TokenType) -> str:
    """Sign a token for `account_id`; every call gets a fresh `jti`."""
    key = _secret_for(settings, token_type)
    issued_at = datetime.now(UTC)
    payload = {
        "sub": account_id,
        "jti": uuid.uuid4().hex,
        "typ": token_type.value,
        "iat": issued_at,
        "exp": issued_at + _lifetime(settings, token_type),
    }
    return jwt.encode(payload, key, algorithm=ALGORITHM)


def verify_token(settings: Settings, token: str, token_type: TokenType) -> TokenClaims:
    """Check signature, expiry and claims; any failure is `UnauthorizedError` without the token in it."""
    key = _secret_for(settings, token_type)
    try:
        payload = jwt.decode(
            token,
            key,
            # Pinned: the header's `alg` is never trusted (blocks `none` and algorithm swaps).
            algorithms=[ALGORITHM],
            options={"require": _REQUIRED_CLAIMS},
        )
    except jwt.PyJWTError:
        # The reason (expired, tampered, malformed) is not told to the client; `from None`
        # keeps the library's message out of the chain.
        raise UnauthorizedError from None

    subject, jti = payload.get("sub"), payload.get("jti")
    if (
        payload.get("typ") != token_type.value
        or not isinstance(subject, str)
        or not isinstance(jti, str)
        or not _is_uuid(subject)
    ):
        raise UnauthorizedError
    return TokenClaims(account_id=subject, jti=jti)


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True
