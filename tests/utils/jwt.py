"""Fake token secrets for tests that need a Settings the strict environments accept."""

from pydantic import SecretStr

# 32+ characters and different, as development and production require (task 4.4).
ACCESS_KEY = SecretStr("test-access-secret-0123456789abcdef")
REFRESH_KEY = SecretStr("test-refresh-secret-0123456789abcdef")
