"""The file and notification models on a real Postgres (rule P8): a round trip and the refusals.

The indexes, foreign-key actions and enum types of these tables are asserted in test_db_account_models.py,
which owns the closed set for the whole schema. The tables live in a throwaway schema made for each test,
so a developer's own tables are never touched and nothing is dropped except that schema.
"""

import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import selectinload
from sqlalchemy.schema import CreateSchema, DropSchema

from app.config import Settings
from app.core.db import Base, create_engine, create_session_factory, utc_now
from app.models import (
    Account,
    AccountProfile,
    File,
    Notification,
    NotificationRecipient,
)

OWN_SCHEMA_PREFIX = "poc_file_models_"
OWN_SCHEMAS = f"{OWN_SCHEMA_PREFIX}%"
# The sibling suite builds the same tables in schemas of its own; what it leaves behind after a
# crash is a test leftover too, not a developer's table (test_db_account_models.py does not
# return the favour, so a leftover of this suite still blocks that one until it is dropped).
SIBLING_SCHEMAS = "poc_account_models_%"

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + bytes(range(256))


@dataclass
class Database:
    engine: AsyncEngine  # every statement is translated into `schema`
    schema: str


@pytest.fixture
async def database(database_url: str) -> AsyncIterator[Database]:
    """All tables and enum types created in a schema of their own, dropped after the test."""
    base_engine = create_engine(Settings(database_url=database_url))
    assert base_engine is not None
    async with base_engine.connect() as connection:
        # A schema left by a crashed earlier run of this suite is its own leftover, not a
        # developer's table, so it must not make every later run fail.
        found = (
            await connection.execute(
                text(
                    "select table_schema, table_name from information_schema.tables "
                    "where table_name in ('File', 'Notification', 'Account') "
                    "and table_schema not like :own and table_schema not like :sibling"
                ),
                {"own": OWN_SCHEMAS, "sibling": SIBLING_SCHEMAS},
            )
        ).all()
    if found:
        # Not a skip and not a drop: these tests only ever remove what they created.
        pytest.fail(
            f"the test database already holds {[tuple(row) for row in found]}; "
            "point TEST_DATABASE_URL at a scratch database (docs/RUNBOOK.md)",
            pytrace=False,
        )

    schema = f"{OWN_SCHEMA_PREFIX}{uuid.uuid4().hex[:8]}"
    async with base_engine.begin() as connection:
        await connection.execute(CreateSchema(schema))
    engine = base_engine.execution_options(schema_translate_map={None: schema})
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        yield Database(engine=engine, schema=schema)
    finally:
        async with base_engine.begin() as connection:
            await connection.execute(DropSchema(schema, cascade=True, if_exists=True))
        await base_engine.dispose()


@dataclass
class Seeded:
    account_id: str
    file_id: str
    notification_id: str


@pytest.fixture
async def seeded(database: Database) -> Seeded:
    """One account with a file it created, a notification sent to it and no profile yet, committed."""
    factory = create_session_factory(database.engine)
    async with factory() as session:
        account = Account(last_login_at=utc_now())
        file = File(
            created_by=account,
            name="avatar.png",
            mime_type="image/png",
            size=len(PNG_BYTES),
            content=PNG_BYTES,
        )
        notification = Notification(message="Welcome", type="WELCOME")
        session.add_all(
            [
                account,
                file,
                notification,
                NotificationRecipient(notification=notification, account=account),
            ]
        )
        await session.commit()
        return Seeded(
            account_id=account.id, file_id=file.id, notification_id=notification.id
        )


async def test_an_avatar_a_file_list_and_a_notification_are_read_back_through_the_relationships(
    database: Database, seeded: Seeded
) -> None:
    factory = create_session_factory(database.engine)
    async with factory() as session:
        session.add(
            AccountProfile(account_id=seeded.account_id, avatar_id=seeded.file_id)
        )
        await session.commit()

    async with factory() as session:
        account = await session.get(
            Account,
            seeded.account_id,
            options=[
                selectinload(Account.profile).selectinload(AccountProfile.avatar),
                selectinload(Account.files),
                selectinload(Account.notification_recipients).selectinload(
                    NotificationRecipient.notification
                ),
            ],
        )

        assert account is not None
        assert account.profile is not None
        assert account.profile.avatar is not None
        assert account.profile.avatar.id == seeded.file_id
        assert account.profile.avatar.content == PNG_BYTES
        assert [file.name for file in account.files] == ["avatar.png"]
        assert [
            link.notification.message for link in account.notification_recipients
        ] == ["Welcome"]


async def test_a_new_file_gets_its_defaults_and_an_update_time(
    database: Database,
) -> None:
    factory = create_session_factory(database.engine)
    async with factory() as session:
        account = Account(last_login_at=utc_now())
        file = File(created_by=account)
        session.add_all([account, file])
        await session.commit()
        file_id = file.id

    async with factory() as session:
        stored = await session.get(File, file_id)

        assert stored is not None
        assert (stored.size, stored.deleted, stored.content, stored.mime_type) == (
            0,
            False,
            None,
            None,
        )
        assert stored.updated_at is not None
        # UTC "now" (the session time zone is UTC); a wide window keeps this clock-proof.
        assert abs(utc_now() - stored.created_at) < timedelta(minutes=5)


async def test_the_bytes_of_a_file_are_replaced_and_the_update_time_moves(
    database: Database, seeded: Seeded
) -> None:
    long_ago = datetime(2000, 1, 1)
    factory = create_session_factory(database.engine)
    async with factory() as session:
        # Backdated so that "moved" is a strict comparison: an insert and an update can land in
        # the same millisecond of a timestamp(3). Setting the column explicitly bypasses onupdate.
        await session.execute(
            update(File).where(File.id == seeded.file_id).values(updated_at=long_ago)
        )
        await session.commit()

    async with factory() as session:
        file = await session.get(File, seeded.file_id)
        assert file is not None
        file.content = b"new bytes"
        await session.commit()

    async with factory() as session:
        stored = await session.get(File, seeded.file_id)

        assert stored is not None
        assert stored.content == b"new bytes"
        assert stored.updated_at is not None
        assert stored.updated_at > long_ago


def _profile_with_avatar(avatar_id: str) -> list[object]:
    """A profile of a second account, so the only broken rule is the avatar."""
    other = Account(last_login_at=utc_now())
    return [other, AccountProfile(account=other, avatar_id=avatar_id)]


# offence -> (the rows that break one rule, the constraint Postgres must name). Built lazily: every row
# links to its neighbours, so an unused one would be pulled into the session and fail on another rule.
OFFENCES: dict[str, tuple[Callable[[Seeded], list[object]], str]] = {
    "file_of_a_missing_creator": (
        lambda s: [File(created_by_id="no-such-account")],
        "File_createdById_fkey",
    ),
    "avatar_naming_a_missing_file": (
        lambda s: _profile_with_avatar("no-such-file"),
        "AccountProfile_avatarId_fkey",
    ),
    "recipient_of_a_missing_notification": (
        lambda s: [
            NotificationRecipient(
                notification_id="no-such-notification", account_id=s.account_id
            )
        ],
        "NotificationRecipient_notificationId_fkey",
    ),
    "recipient_that_is_a_missing_account": (
        lambda s: [
            NotificationRecipient(
                notification_id=s.notification_id, account_id="no-such-account"
            )
        ],
        "NotificationRecipient_accountId_fkey",
    ),
    "second_row_for_the_same_recipient_pair": (
        lambda s: [
            NotificationRecipient(
                notification_id=s.notification_id, account_id=s.account_id
            )
        ],
        "NotificationRecipient_pkey",
    ),
}


@pytest.mark.parametrize("offence", OFFENCES)
async def test_the_database_refuses(
    database: Database, seeded: Seeded, offence: str
) -> None:
    build_rows, constraint = OFFENCES[offence]
    factory = create_session_factory(database.engine)

    async with factory() as session:
        session.add_all(build_rows(seeded))

        with pytest.raises(IntegrityError, match=constraint):
            await session.flush()
