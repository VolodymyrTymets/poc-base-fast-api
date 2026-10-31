"""JSON log lines with sensitive values redacted. Tasks: 1.6.

Redaction is best effort (rule P4): it catches the shapes below, it does not make it safe
to log a secret. It errs towards over-matching: `tokens=5` is redacted too. It runs in the formatter on the final message, the extra fields and the
traceback, so no handler that uses the formatter can skip it. Sentry events go through
the same functions (app/core/sentry.py).
"""

import json
import logging
import re
import sys
from collections.abc import Mapping
from datetime import UTC, datetime

REDACTED = "[REDACTED]"

# Keys are compared lower-cased with "-" and "_" removed, so "x-refresh-token",
# "refreshToken" and "refresh_token" are one spelling. The short name dob must match
# exactly: as substrings they would hit words such as "classname".
_EXACT_KEYS = frozenset({"dob", "dateofbirth", "dataofbirth", "birthdate", "birthday"})
_SUBSTRING_KEYS = (
    "password",
    "token",
    "secret",
    "authorization",
    "cookie",
    "phone",
    "apikey",
)

# A key name inside free text, followed by = or : and its value: password=x, "dob": "1",
# phone: +1 555 ... The value is one quoted string or one run without separators.
_KEY_NAME = (
    r"[\w-]*(?:password|token|secret|apikey)[\w-]*"
    r"|[\w-]*phone[\w-]*|dob|(?:date|data)_?of_?birth|birth_?date|birthday"
)
# Headers whose value is several words ("Basic dXNlcg==", "a=1; session=x") go to the end of
# the line instead of the first space.
_LINE_KEY_NAME = r"[\w-]*(?:authorization|cookie)[\w-]*"
_VALUE = r"""\[REDACTED\]|"[^"]*"|'[^']*'"""
_KEY_VALUE = re.compile(
    rf"""(?P<key>(?P<q>["']?)(?:{_KEY_NAME})(?P=q)\s*[=:]\s*)"""
    rf"""(?P<value>{_VALUE}|\+?\(?\d[\d\s().-]*\d|[^\s,;&}}\]]+)""",
    re.IGNORECASE,
)
_LINE_KEY_VALUE = re.compile(
    rf"""(?P<key>(?P<q>["']?)(?:{_LINE_KEY_NAME})(?P=q)\s*[=:]\s*)"""
    rf"""(?P<value>{_VALUE}|[^\r\n]+)""",
    re.IGNORECASE,
)
_BEARER = re.compile(r"\bbearer\s+[\w.~+/=-]+", re.IGNORECASE)
_JWT = re.compile(r"\beyJ[\w-]+\.[\w-]+\.[\w-]+")
# International format only (+ and 8 to 15 digits with common separators).
_PHONE = re.compile(r"\+\d[\d\s().-]{6,}\d")


def is_sensitive_key(key: object) -> bool:
    name = str(key).lower().replace("-", "").replace("_", "")
    return name in _EXACT_KEYS or any(part in name for part in _SUBSTRING_KEYS)


def redact(text: str) -> str:
    """Replace every sensitive shape in `text`; everything else is returned unchanged."""
    text = _BEARER.sub(REDACTED, text)
    text = _JWT.sub(REDACTED, text)
    text = _LINE_KEY_VALUE.sub(lambda match: match["key"] + REDACTED, text)
    text = _KEY_VALUE.sub(lambda match: match["key"] + REDACTED, text)
    return _PHONE.sub(REDACTED, text)


def redact_mapping(value: object) -> object:
    """Redact nested dicts, lists and strings: a sensitive key hides its whole value."""
    if isinstance(value, Mapping):
        return {
            key: REDACTED if is_sensitive_key(key) else redact_mapping(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple | set | frozenset):
        return [redact_mapping(item) for item in value]
    if isinstance(value, str):
        return redact(value)
    return value


# Attributes every LogRecord has; anything else on the record came from `extra=`.
# uvicorn adds `color_message`, a copy of the message with ANSI colour codes: noise in JSON.
_RECORD_FIELDS = frozenset(vars(logging.makeLogRecord({}))) | {
    "message",
    "asctime",
    "color_message",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        for key, value in vars(record).items():
            if key not in _RECORD_FIELDS:
                entry[key] = (
                    REDACTED if is_sensitive_key(key) else redact_mapping(value)
                )
        if record.exc_info:
            entry["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(
            entry, default=lambda obj: redact(str(obj)), ensure_ascii=False
        )


def configure_logging(level: str) -> None:
    """Send every log record, uvicorn's included, to stdout as redacted JSON lines."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # uvicorn installs its own handlers; dropping them lets its records reach the root.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
