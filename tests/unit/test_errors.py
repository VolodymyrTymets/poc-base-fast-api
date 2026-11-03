import pytest

from app.core.errors import (
    AppError,
    EmailAlreadyRegisteredError,
    ErrorCode,
    ForbiddenError,
    InvalidCredentialsError,
    InvalidResetTokenError,
    NotFoundError,
    PayloadTooLargeError,
    UnauthorizedError,
    ValidationFailedError,
    error_body,
)

CASES: list[tuple[type[AppError], int, ErrorCode]] = [
    (UnauthorizedError, 401, ErrorCode.UNAUTHORIZED),
    (InvalidCredentialsError, 401, ErrorCode.INVALID_CREDENTIALS),
    (InvalidResetTokenError, 400, ErrorCode.INVALID_RESET_TOKEN),
    (EmailAlreadyRegisteredError, 409, ErrorCode.EMAIL_ALREADY_REGISTERED),
    (ForbiddenError, 403, ErrorCode.FORBIDDEN),
    (NotFoundError, 404, ErrorCode.NOT_FOUND),
    (ValidationFailedError, 422, ErrorCode.VALIDATION_FAILED),
    (PayloadTooLargeError, 413, ErrorCode.VALIDATION_FAILED),
]


@pytest.mark.parametrize(("error_class", "status", "code"), CASES)
def test_error_class_carries_its_status_and_code(
    error_class: type[AppError], status: int, code: ErrorCode
) -> None:
    error = error_class()

    assert (error.status_code, error.code) == (status, code)
    assert error.body() == {
        "error": {"code": code.value, "message": error.message, "details": []}
    }


def test_error_body_has_the_three_keys() -> None:
    body = error_body(ErrorCode.NOT_FOUND, "Nothing here", [{"field": "id"}])

    assert body == {
        "error": {
            "code": "NOT_FOUND",
            "message": "Nothing here",
            "details": [{"field": "id"}],
        }
    }


def test_message_and_details_can_be_overridden() -> None:
    error = ForbiddenError("Not your account", [{"field": "accountId"}])

    assert error.body()["error"]["message"] == "Not your account"
    assert error.body()["error"]["details"] == [{"field": "accountId"}]


def test_two_errors_never_share_a_details_list() -> None:
    first = NotFoundError()
    second = NotFoundError()

    first.details.append("only on the first")

    assert second.details == []
