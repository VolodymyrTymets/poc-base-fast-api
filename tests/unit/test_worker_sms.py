import json
import logging
from typing import Any

import pytest

from app.core.logging import JsonFormatter
from app.workers.sms import mask_phone, send_totp_code

PHONE = "+380000000001"
CODE = "482913"


def _lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The final JSON lines, as the worker prints them, not the raw records."""
    formatter = JsonFormatter()
    return [formatter.format(record) for record in caplog.records]


@pytest.mark.parametrize(
    ("phone", "masked"),
    [
        (PHONE, "***0001"),
        ("+380 (00) 000-0001", "***0001"),
        ("12345", "***2345"),
        ("1234", "***"),
        ("abc", "***"),
        ("", "***"),
    ],
)
def test_mask_phone_keeps_at_most_the_last_four_digits(phone: str, masked: str) -> None:
    assert mask_phone(phone) == masked


async def test_the_job_logs_the_masked_phone_and_never_the_number_or_the_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    await send_totp_code({}, PHONE, CODE)

    text = "\n".join(_lines(caplog))
    assert json.loads(text)["message"] == "[SMS] TOTP code sent to ***0001"
    assert PHONE not in text
    assert "0000000" not in text
    assert CODE not in text


async def test_a_repeated_job_logs_the_same_line_again_without_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    ctx: dict[str, Any] = {"job_try": 1}

    await send_totp_code(ctx, PHONE, CODE)
    await send_totp_code(ctx, PHONE, CODE)

    messages = [json.loads(line)["message"] for line in _lines(caplog)]
    assert messages == ["[SMS] TOTP code sent to ***0001"] * 2
