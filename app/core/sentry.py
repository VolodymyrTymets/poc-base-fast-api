"""Sentry error reporting, off for `local` and when no DSN is set. Tasks: 1.6 (ADR-0013).

Sentry's own integrations read log records and requests outside our log formatter, so
everything that leaves the process goes through `before_send` and `before_breadcrumb`,
which apply the same redaction as the log lines (app/core/logging.py).
"""

from typing import cast

from sentry_sdk import init as sentry_init
from sentry_sdk.types import (
    Breadcrumb,
    BreadcrumbHint,
    DataCollectionUserOptions,
    Event,
    Hint,
)

from app.config import Settings
from app.core.logging import redact_mapping

# Nothing an integration collects on its own is sent: no user info, cookies, request headers,
# bodies, query strings or stack-frame variables. `data_collection` replaces the deprecated
# send_default_pii, include_local_variables and max_request_body_size, and does the same job.
DATA_COLLECTION: DataCollectionUserOptions = {
    "user_info": False,
    "cookies": {"mode": "off"},
    "http_headers": {"request": {"mode": "off"}},
    "http_bodies": [],
    "url_query_params": {"mode": "off"},
    "stack_frame_variables": False,
}


# WHY: redact_mapping returns a dict with the same keys and nesting as its input, but the SDK
# types Event and Breadcrumb as TypedDicts that mypy cannot build from a plain dict (POC-1.6).
def scrub_event(event: Event, _hint: Hint) -> Event | None:
    redacted = redact_mapping(event)
    # Returning None drops the event: if the shape is ever not a dict, nothing is sent.
    return cast(Event, redacted) if isinstance(redacted, dict) else None


def scrub_breadcrumb(crumb: Breadcrumb, _hint: BreadcrumbHint) -> Breadcrumb | None:
    redacted = redact_mapping(crumb)
    return cast(Breadcrumb, redacted) if isinstance(redacted, dict) else None


def init_sentry(settings: Settings) -> bool:
    """Start Sentry when the environment and DSN allow it; return whether it started."""
    if settings.app_env == "local" or not settings.sentry_dsn:
        return False
    sentry_init(
        dsn=settings.sentry_dsn,
        environment=settings.app_env,
        data_collection=DATA_COLLECTION,
        before_send=scrub_event,
        before_breadcrumb=scrub_breadcrumb,
    )
    return True
