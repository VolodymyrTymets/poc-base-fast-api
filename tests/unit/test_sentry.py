from typing import Any

import pytest
from sentry_sdk.utils import BadDsn

from app.config import Settings
from app.core import sentry
from app.core.logging import REDACTED

DSN = "https://key@o1.ingest.sentry.io/1"
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl"


@pytest.fixture
def init_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(sentry, "sentry_init", lambda **kwargs: calls.append(kwargs))
    return calls


@pytest.mark.parametrize(
    "settings",
    [
        Settings(app_env="local", sentry_dsn=DSN),
        Settings(app_env="production", sentry_dsn=None),
        Settings(app_env="production", sentry_dsn="  "),
    ],
    ids=["local-with-dsn", "no-dsn", "blank-dsn"],
)
def test_sentry_stays_off(settings: Settings, init_calls: list[dict[str, Any]]) -> None:
    assert sentry.init_sentry(settings) is False
    assert init_calls == []


def test_sentry_starts_with_nothing_collected_by_default(
    init_calls: list[dict[str, Any]],
) -> None:
    started = sentry.init_sentry(Settings(app_env="production", sentry_dsn=DSN))

    assert started is True
    assert len(init_calls) == 1
    options = init_calls[0]
    assert options["dsn"] == DSN
    assert options["environment"] == "production"
    assert options["data_collection"] == {
        "user_info": False,
        "cookies": {"mode": "off"},
        "http_headers": {"request": {"mode": "off"}},
        "http_bodies": [],
        "url_query_params": {"mode": "off"},
        "stack_frame_variables": False,
    }
    assert options["before_send"] is sentry.scrub_event
    assert options["before_breadcrumb"] is sentry.scrub_breadcrumb


def test_a_malformed_dsn_stops_the_boot() -> None:
    with pytest.raises(BadDsn):
        sentry.init_sentry(Settings(app_env="production", sentry_dsn="not-a-dsn"))


def test_scrub_event_redacts_every_part_of_the_event() -> None:
    event: Any = {
        "message": f"failed with {JWT}",
        "request": {
            "data": {
                "password": "hunter2",
                "phone": "+15550109999",
            },
            "headers": {"x-refresh-token": "abc123", "accept": "application/json"},
            "query_string": f"token={JWT}&page=2",
        },
        "extra": {"dob": "1990-01-31"},
        "contexts": {"auth": {"secret": "s3"}},
        "tags": {"phone_number": "+15550109999"},
    }

    result = sentry.scrub_event(event, {})

    assert result == {
        "message": f"failed with {REDACTED}",
        "request": {
            "data": {"password": REDACTED, "phone": REDACTED},
            "headers": {"x-refresh-token": REDACTED, "accept": "application/json"},
            "query_string": f"token={REDACTED}&page=2",
        },
        "extra": {"dob": REDACTED},
        "contexts": {"auth": {"secret": REDACTED}},
        "tags": {"phone_number": REDACTED},
    }


def test_scrub_event_drops_raw_log_arguments_and_keeps_the_redacted_text() -> None:
    event: Any = {
        "logentry": {
            "message": "reset failed phone=%s",
            "formatted": "reset failed phone=+15550109999",
            "params": ["+15550109999"],
        }
    }

    result = sentry.scrub_event(event, {})

    assert result == {
        "logentry": {
            "message": f"reset failed phone={REDACTED}",
            "formatted": f"reset failed phone={REDACTED}",
        }
    }


def test_scrub_breadcrumb_redacts_its_data() -> None:
    crumb: Any = {
        "category": "log",
        "message": "refreshing",
        "data": {"note": f"saw {JWT}", "authorization": "Bearer abc"},
    }

    assert sentry.scrub_breadcrumb(crumb, {}) == {
        "category": "log",
        "message": "refreshing",
        "data": {"note": f"saw {REDACTED}", "authorization": REDACTED},
    }
