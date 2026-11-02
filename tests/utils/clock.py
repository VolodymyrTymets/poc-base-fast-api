"""The instant the `frozen_clock` fixture moves the process clock to."""

from datetime import UTC, datetime

FROZEN_NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
