"""The seed item contract and the error the runner raises. Task: 5.1."""

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession


class SeedError(RuntimeError):
    """A seed item failed; the cause is chained and its text is in `SeedHistory.result`."""


class SeedItem(Protocol):
    """One piece of base data. The runner calls both methods inside one transaction it owns:
    an item never commits, and whatever `run` wrote is rolled back if it raises."""

    @property
    def name(self) -> str:
        """Unique and stable: it is the key of the item's `SeedHistory` row."""
        ...

    async def needs_to_run(self, session: AsyncSession) -> bool: ...

    async def run(self, session: AsyncSession) -> None: ...
