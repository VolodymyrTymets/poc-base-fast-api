import json
import logging
import sys
from collections.abc import Iterator

import pytest

from app.core.logging import (
    REDACTED,
    JsonFormatter,
    configure_logging,
    redact,
    redact_mapping,
)

JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl"


@pytest.mark.parametrize(
    ("text", "leaked"),
    [
        (f"token={JWT}", JWT),
        (f"refresh {JWT} failed", JWT),
        ("Authorization: Bearer abc.def-123", "abc.def-123"),
        ("password=hunter2 ok", "hunter2"),
        ('{"password": "hunter2"}', "hunter2"),
        ("login with ssn 123-45-6789", "123-45-6789"),
        ('{"ssn": "999"}', "999"),
        ("dob=1990-01-31", "1990-01-31"),
        ("call +1 (555) 010-9999 now", "555"),
        ("phoneNumber: 5550109999", "5550109999"),
        ("x-refresh-token: abc123", "abc123"),
        ("Authorization: Basic dXNlcjpwYXNz", "dXNlcjpwYXNz"),
        ("Cookie: a=1; session=SECRET", "SECRET"),
        ("phone: (555) 010-9999", "010-9999"),
        ("phone=555 010 9999", "010 9999"),
        ("birthDate: 1990-01-31", "1990-01-31"),
        ("user_ssn=123456789", "123456789"),
    ],
    ids=[
        "jwt-key",
        "jwt-shape",
        "bearer",
        "password-pair",
        "password-json",
        "ssn-shape",
        "ssn-json",
        "dob",
        "phone-shape",
        "phone-key",
        "refresh-header",
        "basic-auth",
        "cookie-line",
        "phone-parens",
        "phone-spaces",
        "birth-date",
        "ssn-suffix",
    ],
)
def test_redact_removes_the_sensitive_value(text: str, leaked: str) -> None:
    result = redact(text)

    assert leaked not in result
    assert REDACTED in result


@pytest.mark.parametrize(
    "text",
    ["GET /api/v1/health 200", "classname=Foo user 42 logged in", "port 3001 ready"],
)
def test_redact_leaves_other_text_alone(text: str) -> None:
    assert redact(text) == text


def test_redact_mapping_hides_values_by_key_and_by_shape() -> None:
    result = redact_mapping(
        {
            "password": "hunter2",
            "birthDate": "1990-01-31",
            "user_ssn": "123",
            "nested": {"X-Refresh-Token": "abc", "note": f"saw {JWT}"},
            "items": [{"ssn": "123-45-6789"}, "ok"],
            "count": 3,
        }
    )

    assert result == {
        "password": REDACTED,
        "birthDate": REDACTED,
        "user_ssn": REDACTED,
        "nested": {"X-Refresh-Token": REDACTED, "note": f"saw {REDACTED}"},
        "items": [{"ssn": REDACTED}, "ok"],
        "count": 3,
    }


def make_record(message: str, **extra: object) -> logging.LogRecord:
    return logging.makeLogRecord(
        {
            "name": "app.test",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "msg": message,
            **extra,
        }
    )


def test_formatter_writes_one_json_object_with_the_four_fields() -> None:
    line = JsonFormatter().format(make_record("hello"))

    entry = json.loads(line)
    assert "\n" not in line
    assert {k: entry[k] for k in ("level", "logger", "message")} == {
        "level": "INFO",
        "logger": "app.test",
        "message": "hello",
    }
    assert entry["timestamp"]


def test_formatter_redacts_message_args_and_extra() -> None:
    record = make_record(
        "signed in with %s", args=(JWT,), user={"phone": "+15550109999"}, note=JWT
    )

    entry = json.loads(JsonFormatter().format(record))

    assert entry["message"] == f"signed in with {REDACTED}"
    assert entry["user"] == {"phone": REDACTED}
    assert entry["note"] == REDACTED


def test_formatter_redacts_a_traceback() -> None:
    try:
        raise ValueError(f"bad token {JWT}")
    except ValueError:
        record = make_record("failed", exc_info=sys.exc_info())

    entry = json.loads(JsonFormatter().format(record))

    assert JWT not in entry["exception"]
    assert "ValueError" in entry["exception"]


@pytest.fixture
def restore_root_logger() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers, root.level = handlers, level


@pytest.mark.usefixtures("restore_root_logger")
def test_configure_logging_prints_redacted_json_to_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO")

    logging.getLogger("uvicorn.error").info("token=%s", JWT)
    logging.getLogger("app.test").debug("hidden by level")

    lines = capsys.readouterr().out.splitlines()
    assert [json.loads(line)["message"] for line in lines] == [f"token={REDACTED}"]


def test_redact_is_idempotent() -> None:
    once = redact(f"token={JWT} password=x")

    assert redact(once) == once


def test_formatter_drops_uvicorns_colour_copy_of_the_message() -> None:
    record = make_record("Started", color_message="\x1b[36mStarted\x1b[0m")

    assert "color_message" not in json.loads(JsonFormatter().format(record))
