"""The account models on a real Postgres (rule P8): the indexes and foreign keys the database holds, and a round trip.

The tables live in a throwaway schema made for each test, so a developer's own tables are never touched and
nothing is dropped except that schema.
"""

import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import selectinload
from sqlalchemy.schema import CreateSchema, DropSchema

from app.config import Settings
from app.core.db import Base, create_engine, create_session_factory, utc_now
from app.models import (
    Account,
    AccountIdentity,
    AccountOnRole,
    AccountProfile,
    AccountRole,
    AccountRoleType,
)

# A value the seeded identity stores and the offending rows try to repeat.
FIRST_RESET = "reset-1"


@dataclass
class Database:
    engine: AsyncEngine  # every statement is translated into `schema`
    schema: str


@pytest.fixture
async def database(database_url: str) -> AsyncIterator[Database]:
    """The account tables and the enum type created in a schema of their own, dropped after the test."""
    base_engine = create_engine(Settings(database_url=database_url))
    assert base_engine is not None
    async with base_engine.connect() as connection:
        found_tables = (
            await connection.execute(
                text(
                    "select table_schema from information_schema.tables where table_name like 'Account%'"
                )
            )
        ).all()
        found_types = (
            await connection.execute(
                text("select typname from pg_type where typname = 'AccountRoleType'")
            )
        ).all()
    if found_tables or found_types:
        # Not a skip and not a drop: these tests only ever remove what they created.
        pytest.fail(
            f"the test database already holds account objects {[*found_tables, *found_types]}; "
            "point TEST_DATABASE_URL at a scratch database (docs/RUNBOOK.md)",
            pytrace=False,
        )

    schema = f"poc_account_models_{uuid.uuid4().hex[:8]}"
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


# index name -> the definition Postgres reports, with the schema prefix removed. The names, columns,
# uniqueness and order come from the Prisma migrations; the text is how pg_indexes spells them.
INDEX_DEFINITIONS = {
    "Account_pkey": 'CREATE UNIQUE INDEX "Account_pkey" ON "Account" USING btree (id)',
    "AccountRole_pkey": 'CREATE UNIQUE INDEX "AccountRole_pkey" ON "AccountRole" USING btree (id)',
    "AccountOnRole_pkey": 'CREATE UNIQUE INDEX "AccountOnRole_pkey" ON "AccountOnRole" USING btree ("roleId", "accountId")',
    "AccountIdentity_pkey": 'CREATE UNIQUE INDEX "AccountIdentity_pkey" ON "AccountIdentity" USING btree (id)',
    "AccountProfile_pkey": 'CREATE UNIQUE INDEX "AccountProfile_pkey" ON "AccountProfile" USING btree (id)',
    "Account_createdAt_idx": 'CREATE INDEX "Account_createdAt_idx" ON "Account" USING btree ("createdAt" DESC)',
    "AccountRole_type_key": 'CREATE UNIQUE INDEX "AccountRole_type_key" ON "AccountRole" USING btree (type)',
    "AccountRole_type_deleted_idx": 'CREATE INDEX "AccountRole_type_deleted_idx" ON "AccountRole" USING btree (type, deleted)',
    "AccountOnRole_deleted_idx": 'CREATE INDEX "AccountOnRole_deleted_idx" ON "AccountOnRole" USING btree (deleted)',
    "AccountIdentity_accountId_key": 'CREATE UNIQUE INDEX "AccountIdentity_accountId_key" ON "AccountIdentity" USING btree ("accountId")',
    "AccountIdentity_resetTokenHash_key": 'CREATE UNIQUE INDEX "AccountIdentity_resetTokenHash_key" ON "AccountIdentity" USING btree ("resetTokenHash")',
    "AccountIdentity_deleted_idx": 'CREATE INDEX "AccountIdentity_deleted_idx" ON "AccountIdentity" USING btree (deleted)',
    "AccountProfile_accountId_key": 'CREATE UNIQUE INDEX "AccountProfile_accountId_key" ON "AccountProfile" USING btree ("accountId")',
    "AccountProfile_email_key": 'CREATE UNIQUE INDEX "AccountProfile_email_key" ON "AccountProfile" USING btree (email)',
    "AccountProfile_deleted_idx": 'CREATE INDEX "AccountProfile_deleted_idx" ON "AccountProfile" USING btree (deleted)',
}

# pg_constraint codes: r = RESTRICT, c = CASCADE, n = SET NULL.
FOREIGN_KEY_ACTIONS = {
    "Account_lastAccountRoleId_fkey": ("n", "c"),
    "AccountOnRole_roleId_fkey": ("r", "c"),
    "AccountOnRole_accountId_fkey": ("r", "c"),
    "AccountIdentity_accountId_fkey": ("r", "c"),
    "AccountProfile_accountId_fkey": ("r", "c"),
}


async def test_the_database_holds_exactly_the_prisma_indexes(
    database: Database,
) -> None:
    async with database.engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    "select indexname, indexdef from pg_indexes where schemaname = :schema"
                ),
                {"schema": database.schema},
            )
        ).all()

    actual = {
        name: definition.replace(f"{database.schema}.", "") for name, definition in rows
    }

    assert actual == INDEX_DEFINITIONS


async def test_the_database_holds_the_prisma_foreign_key_actions(
    database: Database,
) -> None:
    async with database.engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    "select c.conname, c.confdeltype::text, c.confupdtype::text from pg_constraint c "
                    "join pg_namespace n on n.oid = c.connamespace "
                    "where n.nspname = :schema and c.contype = 'f'"
                ),
                {"schema": database.schema},
            )
        ).all()

    assert {
        name: (on_delete, on_update) for name, on_delete, on_update in rows
    } == FOREIGN_KEY_ACTIONS


@dataclass
class Seeded:
    account_id: str
    role_id: str


@pytest.fixture
async def seeded(database: Database) -> Seeded:
    """One account with an identity, a profile, a role and the link between them, committed."""
    factory = create_session_factory(database.engine)
    async with factory() as session:
        role = AccountRole(type=AccountRoleType.CUSTOMER)
        account = Account(last_login_at=utc_now(), LastAccountRole=role)
        session.add_all(
            [
                account,
                role,
                AccountIdentity(Account=account, reset_token_hash=FIRST_RESET),
                AccountProfile(Account=account, email="first@example.com"),
                AccountOnRole(Account=account, AccountRole=role),
            ]
        )
        await session.commit()
        return Seeded(account_id=account.id, role_id=role.id)


async def test_an_account_graph_is_stored_and_read_back_through_its_relationships(
    database: Database, seeded: Seeded
) -> None:
    factory = create_session_factory(database.engine)

    async with factory() as session:
        account = await session.get(
            Account,
            seeded.account_id,
            options=[
                selectinload(Account.AccountIdentity),
                selectinload(Account.AccountProfile),
                selectinload(Account.AccountOnRole).selectinload(
                    AccountOnRole.AccountRole
                ),
                selectinload(Account.LastAccountRole),
            ],
        )

        assert account is not None
        assert account.AccountIdentity is not None
        assert account.AccountIdentity.reset_token_hash == FIRST_RESET
        assert account.AccountProfile is not None
        assert account.AccountProfile.email == "first@example.com"
        assert [link.AccountRole.type for link in account.AccountOnRole] == [
            AccountRoleType.CUSTOMER
        ]
        assert account.LastAccountRole is not None
        assert account.LastAccountRole.id == seeded.role_id


async def test_a_new_account_gets_its_defaults_and_an_update_time(
    database: Database, seeded: Seeded
) -> None:
    factory = create_session_factory(database.engine)

    async with factory() as session:
        account = await session.get(Account, seeded.account_id)

        assert account is not None
        assert (
            account.deleted,
            account.created_at is not None,
            account.updated_at is not None,
        ) == (
            False,
            True,
            True,
        )


def _account_with(**profile_or_identity: object) -> list[object]:
    """A second account carrying the one row that repeats a value of the seeded account."""
    other = Account(last_login_at=utc_now())
    rows: list[object] = [other]
    if "email" in profile_or_identity:
        rows.append(
            AccountProfile(Account=other, email=str(profile_or_identity["email"]))
        )
    if "reset_token_hash" in profile_or_identity:
        rows.append(
            AccountIdentity(
                Account=other,
                reset_token_hash=str(profile_or_identity["reset_token_hash"]),
            )
        )
    return rows


# offence -> (the rows that break one rule, the constraint Postgres must name). Built lazily: every row
# links to its neighbours, so an unused one would be pulled into the session and fail on another rule.
OFFENCES: dict[str, tuple[Callable[[Seeded], list[object]], str]] = {
    "second_role_of_the_same_type": (
        lambda s: [AccountRole(type=AccountRoleType.CUSTOMER)],
        "AccountRole_type_key",
    ),
    "second_identity_for_the_account": (
        lambda s: [AccountIdentity(account_id=s.account_id)],
        "AccountIdentity_accountId_key",
    ),
    "second_profile_for_the_account": (
        lambda s: [AccountProfile(account_id=s.account_id)],
        "AccountProfile_accountId_key",
    ),
    "repeated_email": (
        lambda s: _account_with(email="first@example.com"),
        "AccountProfile_email_key",
    ),
    "repeated_reset_token_hash": (
        lambda s: _account_with(reset_token_hash=FIRST_RESET),
        "AccountIdentity_resetTokenHash_key",
    ),
    "link_to_a_missing_role": (
        lambda s: [AccountOnRole(account_id=s.account_id, role_id="no-such-role")],
        "AccountOnRole_roleId_fkey",
    ),
    "link_to_a_missing_account": (
        lambda s: [AccountOnRole(account_id="no-such-account", role_id=s.role_id)],
        "AccountOnRole_accountId_fkey",
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
