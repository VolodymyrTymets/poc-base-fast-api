"""An in-memory `CacheStore` for tests that need a read cache without Redis (task 9.2, ADR-0035).

`keys` is deliberately absent: a call to it is an AttributeError, so KEYS cannot slip into the code under test. The real Redis
behaviour is tested in `tests/integration/http/test_http_read_cache.py`.
"""

from collections.abc import AsyncIterator
from fnmatch import fnmatchcase


class MemoryStore:
    def __init__(
        self, fail_with: Exception | None = None, fail_on: str | None = None
    ) -> None:
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.fail_with = fail_with
        self.fail_on = (
            fail_on  # None: every call fails; else only the call of that name
        )
        self.calls: list[str] = []
        self.delete_batches: list[int] = []

    def _check(self, name: str) -> None:
        self.calls.append(name)
        if self.fail_with is not None and self.fail_on in (None, name):
            raise self.fail_with

    async def get(self, key: str) -> str | None:
        self._check("get")
        return self.data.get(key)

    async def set(self, key: str, value: str, *, ex: int) -> None:
        self._check("set")
        self.data[key] = value
        self.ttls[key] = ex

    async def scan_iter(self, match: str) -> AsyncIterator[str]:
        self._check("scan_iter")
        # Redis writes a literal star as `\*`, fnmatch as `[*]`.
        glob = match.replace("\\*", "[*]")
        for key in list(self.data):
            if fnmatchcase(key, glob):
                yield key

    async def delete(self, *keys: str) -> int:
        self._check("delete")
        self.delete_batches.append(len(keys))
        for key in keys:
            self.data.pop(key, None)
        return len(keys)

    async def close(self) -> None:
        self.calls.append("close")
