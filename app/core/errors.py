"""The error contract: domain exceptions and the one body every error uses. Tasks: 4.2 (ADR-0003).

Services raise the subclasses of `AppError`; the handlers (registered from `app/main.py`)
turn them into `{"error": {"code", "message", "details"}}`. Clients key on `code`, never on
`message`. A new code needs a superseding ADR, not just a new subclass.
"""

from collections.abc import Sequence
from enum import StrEnum, auto
from typing import ClassVar, TypedDict

from pydantic import BaseModel

# A validation entry (`field`, `in`, `message`, `type`) or one traceback string: the only
# two things `details` ever holds.
type ErrorDetail = dict[str, str] | str


class ErrorCode(StrEnum):
    # Each value is its own name, the string clients key on. Written with auto() so no
    # member is a string literal that ruff's S105 reads as a hardcoded password.
    @staticmethod
    def _generate_next_value_(
        name: str, start: int, count: int, last_values: list[str]
    ) -> str:
        return name

    UNAUTHORIZED = auto()
    INVALID_CREDENTIALS = auto()
    INVALID_RESET_TOKEN = auto()
    EMAIL_ALREADY_REGISTERED = auto()
    FORBIDDEN = auto()
    NOT_FOUND = auto()
    VALIDATION_FAILED = auto()
    INTERNAL_SERVER_ERROR = auto()


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str
    details: list[ErrorDetail]


class ErrorResponse(BaseModel):
    """The body of every error response; the model the OpenAPI contract points at."""

    error: ErrorBody


class ErrorBodyDict(TypedDict):
    code: str
    message: str
    details: list[ErrorDetail]


class ErrorEnvelope(TypedDict):
    error: ErrorBodyDict


def error_body(
    code: str, message: str, details: Sequence[ErrorDetail] = ()
) -> ErrorEnvelope:
    """The single place the error body is built, also used by middleware that cannot raise."""
    return {"error": {"code": code, "message": message, "details": list(details)}}


class AppError(Exception):
    """Base of the domain errors. Subclasses set the three class attributes."""

    status_code: ClassVar[int]
    code: ClassVar[ErrorCode]
    default_message: ClassVar[str]

    def __init__(
        self, message: str | None = None, details: Sequence[ErrorDetail] = ()
    ) -> None:
        self.message = message or self.default_message
        # Copied so two errors never share one list.
        self.details: list[ErrorDetail] = list(details)
        super().__init__(self.message)

    def body(self) -> ErrorEnvelope:
        return error_body(self.code, self.message, self.details)


class UnauthorizedError(AppError):
    """The token is missing, expired, tampered or maps to no account: the client refreshes."""

    status_code = 401
    code = ErrorCode.UNAUTHORIZED
    default_message = "Authentication required"


class InvalidCredentialsError(AppError):
    """Wrong email or password, or a bad OTP: never a reason to refresh."""

    status_code = 401
    code = ErrorCode.INVALID_CREDENTIALS
    default_message = "Invalid credentials"


class InvalidResetTokenError(AppError):
    status_code = 400
    code = ErrorCode.INVALID_RESET_TOKEN
    default_message = "Invalid or expired reset token"


class EmailAlreadyRegisteredError(AppError):
    status_code = 409
    code = ErrorCode.EMAIL_ALREADY_REGISTERED
    default_message = "Email already registered"


class ForbiddenError(AppError):
    status_code = 403
    code = ErrorCode.FORBIDDEN
    default_message = "Not allowed"


class NotFoundError(AppError):
    status_code = 404
    code = ErrorCode.NOT_FOUND
    default_message = "Not found"


class ValidationFailedError(AppError):
    status_code = 422
    code = ErrorCode.VALIDATION_FAILED
    default_message = "Validation failed"
