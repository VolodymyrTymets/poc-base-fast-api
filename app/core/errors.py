"""The error contract: domain exceptions and the one body every error uses. Tasks: 4.2 (ADR-0003).

Services raise the subclasses of `AppError`; the handlers (registered from `app/main.py`)
turn them into `{"error": {"code", "message", "details"}}`. Clients key on `code`, never on
`message`. A new code needs a superseding ADR, not just a new subclass.
"""

import logging
import traceback
from collections.abc import Sequence
from enum import StrEnum, auto
from typing import ClassVar, TypedDict

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

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


class InternalServerError(AppError):
    """Raised by nobody: the handler of an unexpected exception builds it for the body."""

    status_code = 500
    code = ErrorCode.INTERNAL_SERVER_ERROR
    default_message = "Internal server error"


class ValidationFailedError(AppError):
    status_code = 422
    code = ErrorCode.VALIDATION_FAILED
    default_message = "Validation failed"


# HTTP statuses raised by Starlette or a dependency (HTTPException) that have a code of
# their own. Any other status keeps its number and is reported as VALIDATION_FAILED
# (decided with the owner on 2026-11-03, no new code: ADR-0003).
_HTTP_STATUS_ERRORS: dict[int, type[AppError]] = {
    401: UnauthorizedError,
    403: ForbiddenError,
    404: NotFoundError,
}


def validation_details(exc: RequestValidationError) -> list[ErrorDetail]:
    """One entry per failed field: where it is, which field, why. Never the submitted value.

    Pydantic's own error dicts carry `input` (a password in a sign-up body) and `ctx`, so
    only `loc`, `msg` and `type` are read (rules D8, P4).
    """
    details: list[ErrorDetail] = []
    for error in exc.errors():
        location = [str(part) for part in error["loc"]]
        details.append(
            {
                "in": location[0] if location else "",
                "field": ".".join(location[1:]),
                "message": str(error["msg"]),
                "type": str(error["type"]),
            }
        )
    return details


def register_error_handlers(app: FastAPI, *, expose_trace: bool) -> None:
    """Make every error leave `app` in the contract shape.

    `expose_trace` puts the traceback of an unexpected error in `details`; it is for the
    `local` environment only, the caller decides.
    """

    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(exc.body(), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        error = ValidationFailedError(details=validation_details(exc))
        return JSONResponse(error.body(), status_code=error.status_code)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        known = _HTTP_STATUS_ERRORS.get(exc.status_code)
        if known is not None:
            error = known()
            status = error.status_code
        else:
            error = ValidationFailedError(exc.detail)
            status = exc.status_code
        # Headers matter: a 405 carries `Allow`, a 401 may carry `WWW-Authenticate`.
        return JSONResponse(error.body(), status_code=status, headers=exc.headers)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # The stack goes to the log in every environment, never into the body outside local.
        # No body, headers or query string are logged (rules D8, P4).
        logger.error(
            "unhandled error on %s %s", request.method, request.url.path, exc_info=exc
        )
        details: list[ErrorDetail] = []
        if expose_trace:
            details.append("".join(traceback.format_exception(exc)))
        error = InternalServerError(details=details)
        return JSONResponse(error.body(), status_code=error.status_code)
