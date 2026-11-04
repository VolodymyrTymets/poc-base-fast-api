import json
import logging
from collections.abc import Iterator

import pytest

from app.config import get_settings
from app.core.logging import JsonFormatter
from app.workers.email import send_password_reset

ACCOUNT_ID = "account-1"
EMAIL = "reset.me@example.test"
RESET_VALUE = "fake-reset-token-0001"


@pytest.fixture
def set_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    """Settings are cached, so the cache is cleared around each environment change."""
    # development and production refuse to boot without both secrets (config.py).
    monkeypatch.setenv("JWT_SECRET", "a" * 32)
    monkeypatch.setenv("JWT_REFRESH_TOKEN_SECRET", "b" * 32)
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


def _lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The final JSON lines, as the worker prints them: this includes the redaction."""
    formatter = JsonFormatter()
    return [formatter.format(record) for record in caplog.records]


@pytest.mark.parametrize("env", ["local", "development", "test"])
async def test_adr_0026_logs_the_recipient_and_token_so_the_flow_can_be_finished_by_hand(
    env: str, set_env: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    set_env.setenv("APP_ENV", env)
    caplog.set_level(logging.INFO)

    await send_password_reset({}, ACCOUNT_ID, EMAIL, RESET_VALUE)

    # Fails if `redact` ever starts matching `token <value>`: ADR-0026 then needs a new decision.
    assert [json.loads(line)["message"] for line in _lines(caplog)] == [
        f"[EMAIL] Password reset for {EMAIL} (account {ACCOUNT_ID}): token {RESET_VALUE}"
    ]


async def test_production_logs_only_the_account_id(
    set_env: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    set_env.setenv("APP_ENV", "production")
    caplog.set_level(logging.INFO)

    await send_password_reset({}, ACCOUNT_ID, EMAIL, RESET_VALUE)

    text = "\n".join(_lines(caplog))
    assert ACCOUNT_ID in text
    assert EMAIL not in text
    assert RESET_VALUE not in text


async def test_a_repeated_job_logs_the_same_line_again_without_error(
    set_env: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    set_env.setenv("APP_ENV", "test")
    caplog.set_level(logging.INFO)

    await send_password_reset({}, ACCOUNT_ID, EMAIL, RESET_VALUE)
    await send_password_reset({}, ACCOUNT_ID, EMAIL, RESET_VALUE)

    messages = [json.loads(line)["message"] for line in _lines(caplog)]
    assert len(messages) == 2
    assert messages[0] == messages[1]
