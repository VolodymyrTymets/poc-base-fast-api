"""The account tables against the DDL Prisma emitted (../poc-base init and kan_12 migrations). No database."""

from typing import Any

import pytest
from sqlalchemy import Column, Enum, Table, inspect
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import CreateIndex, CreateTable, DefaultClause

from app.core.db import Base
from app.models import (
    Account,
    AccountIdentity,
    AccountOnRole,
    AccountProfile,
    AccountRole,
    AccountRoleType,
)

# The dialect the DDL is compiled for; an engine opens no connection until it is used.
POSTGRES = create_async_engine("postgresql+asyncpg://").dialect

TS = "TIMESTAMP(3) WITHOUT TIME ZONE"
FALSE = "false"

# column name -> (compiled type, nullable, server default). Column order is not compared:
# the Alembic revision of task 2.4 fixes it by hand.
COLUMNS: dict[str, dict[str, tuple[str, bool, str | None]]] = {
    "Account": {
        "id": ("TEXT", False, None),
        "createdAt": (TS, False, "CURRENT_TIMESTAMP"),
        "updatedAt": (TS, True, None),
        "deleted": ("BOOLEAN", False, FALSE),
        "lastLoginAt": (TS, False, None),
        "lastAccountRoleId": ("TEXT", True, None),
    },
    "AccountRole": {
        "id": ("TEXT", False, None),
        "type": ('"AccountRoleType"', False, None),
        "deleted": ("BOOLEAN", False, FALSE),
    },
    "AccountOnRole": {
        "roleId": ("TEXT", False, None),
        "accountId": ("TEXT", False, None),
        "deleted": ("BOOLEAN", False, FALSE),
    },
    "AccountIdentity": {
        "id": ("TEXT", False, None),
        "accountId": ("TEXT", False, None),
        "hash": ("TEXT", True, None),
        "salt": ("TEXT", True, None),
        "otpHash": ("TEXT", True, None),
        "otpSalt": ("TEXT", True, None),
        "otpExpiresAt": (TS, True, None),
        "resetTokenHash": ("TEXT", True, None),
        "resetTokenExpiresAt": (TS, True, None),
        "refreshToken": ("TEXT", True, None),
        "deleted": ("BOOLEAN", False, FALSE),
    },
    "AccountProfile": {
        "id": ("TEXT", False, None),
        "accountId": ("TEXT", False, None),
        "email": ("TEXT", True, None),
        "phoneNumber": ("TEXT", True, None),
        "isPhoneVerified": ("BOOLEAN", False, FALSE),
        "firstName": ("TEXT", True, None),
        "lastName": ("TEXT", True, None),
        "middleName": ("TEXT", True, None),
        "dataOfBirth": ("TEXT", True, None),
        "SSN": ("TEXT", True, None),
        "deleted": ("BOOLEAN", False, FALSE),
        "is18YearOld": ("BOOLEAN", False, FALSE),
        "avatarId": ("TEXT", True, None),
    },
}

PRIMARY_KEYS = {
    "Account": ("Account_pkey", ["id"]),
    "AccountRole": ("AccountRole_pkey", ["id"]),
    "AccountOnRole": ("AccountOnRole_pkey", ["roleId", "accountId"]),
    "AccountIdentity": ("AccountIdentity_pkey", ["id"]),
    "AccountProfile": ("AccountProfile_pkey", ["id"]),
}

# index name -> (table, columns, unique)
INDEXES: dict[str, tuple[str, list[str], bool]] = {
    "Account_createdAt_idx": ("Account", ["createdAt"], False),
    "AccountRole_type_key": ("AccountRole", ["type"], True),
    "AccountRole_type_deleted_idx": ("AccountRole", ["type", "deleted"], False),
    "AccountOnRole_deleted_idx": ("AccountOnRole", ["deleted"], False),
    "AccountIdentity_accountId_key": ("AccountIdentity", ["accountId"], True),
    "AccountIdentity_resetTokenHash_key": ("AccountIdentity", ["resetTokenHash"], True),
    "AccountIdentity_deleted_idx": ("AccountIdentity", ["deleted"], False),
    "AccountProfile_accountId_key": ("AccountProfile", ["accountId"], True),
    "AccountProfile_email_key": ("AccountProfile", ["email"], True),
    "AccountProfile_deleted_idx": ("AccountProfile", ["deleted"], False),
}

# constraint name -> (table, column, referred table, ON DELETE, ON UPDATE)
FOREIGN_KEYS = {
    "Account_lastAccountRoleId_fkey": (
        "Account",
        "lastAccountRoleId",
        "AccountRole",
        "SET NULL",
        "CASCADE",
    ),
    "AccountOnRole_roleId_fkey": (
        "AccountOnRole",
        "roleId",
        "AccountRole",
        "RESTRICT",
        "CASCADE",
    ),
    "AccountOnRole_accountId_fkey": (
        "AccountOnRole",
        "accountId",
        "Account",
        "RESTRICT",
        "CASCADE",
    ),
    "AccountIdentity_accountId_fkey": (
        "AccountIdentity",
        "accountId",
        "Account",
        "RESTRICT",
        "CASCADE",
    ),
    "AccountProfile_accountId_fkey": (
        "AccountProfile",
        "accountId",
        "Account",
        "RESTRICT",
        "CASCADE",
    ),
}


def table(name: str) -> Table:
    return Base.metadata.tables[name]


def server_default(column: Column[Any]) -> str | None:
    default = column.server_default
    if default is None:
        return None
    assert isinstance(default, DefaultClause), f"{column.name}: unexpected {default!r}"
    return str(default.arg)


def test_the_metadata_lists_exactly_the_account_tables() -> None:
    assert set(Base.metadata.tables) == set(COLUMNS)


@pytest.mark.parametrize("name", COLUMNS)
def test_a_table_has_the_prisma_columns_types_nullability_and_defaults(
    name: str,
) -> None:
    actual = {
        column.name: (
            column.type.compile(dialect=POSTGRES),
            column.nullable,
            server_default(column),
        )
        for column in table(name).columns
    }

    assert actual == COLUMNS[name]


@pytest.mark.parametrize("name", PRIMARY_KEYS)
def test_a_table_has_the_prisma_primary_key(name: str) -> None:
    primary_key = table(name).primary_key

    assert (
        primary_key.name,
        [column.name for column in primary_key.columns],
    ) == PRIMARY_KEYS[name]


@pytest.mark.parametrize("name", COLUMNS)
def test_a_table_has_exactly_the_prisma_indexes_and_no_unique_constraint(
    name: str,
) -> None:
    indexes = {
        index.name: (
            name,
            [column.name for column in index.columns],
            bool(index.unique),
        )
        for index in table(name).indexes
    }
    uniques = [
        c for c in table(name).constraints if type(c).__name__ == "UniqueConstraint"
    ]

    assert indexes == {k: v for k, v in INDEXES.items() if v[0] == name}
    assert uniques == []


def test_the_created_at_index_is_descending() -> None:
    (index,) = table("Account").indexes

    assert 'ON "Account" ("createdAt" DESC)' in str(
        CreateIndex(index).compile(dialect=POSTGRES)
    )


@pytest.mark.parametrize("name", FOREIGN_KEYS)
def test_a_foreign_key_has_the_prisma_target_and_actions(name: str) -> None:
    table_name, column, referred, on_delete, on_update = FOREIGN_KEYS[name]
    constraints = {fk.name: fk for fk in table(table_name).foreign_key_constraints}

    fk = constraints[name]

    assert (
        [c.name for c in fk.columns],
        fk.referred_table.name,
        fk.ondelete,
        fk.onupdate,
    ) == ([column], referred, on_delete, on_update)


def test_the_tables_have_no_foreign_key_beyond_the_prisma_ones() -> None:
    actual = {
        fk.name
        for t in Base.metadata.tables.values()
        for fk in t.foreign_key_constraints
    }

    assert actual == set(FOREIGN_KEYS)


def test_the_role_type_enum_is_the_prisma_type() -> None:
    column_type = table("AccountRole").c["type"].type

    assert isinstance(column_type, Enum)
    assert column_type.name == "AccountRoleType"
    assert column_type.enums == ["CUSTOMER", "ADMIN"]
    assert list(AccountRoleType) == ["CUSTOMER", "ADMIN"]


@pytest.mark.parametrize("name", COLUMNS)
def test_create_table_compiles_with_quoted_mixed_case_names(name: str) -> None:
    sql = str(CreateTable(table(name)).compile(dialect=POSTGRES))

    assert sql.startswith(f'\nCREATE TABLE "{name}" (')


MODELS: list[type[Base]] = [
    Account,
    AccountRole,
    AccountOnRole,
    AccountIdentity,
    AccountProfile,
]

# (class, relationship name) -> (target class, name on the other side, is a list).
# The names are Prisma's (scope decision P1), including the lower-case `accounts`.
RELATIONSHIPS: dict[tuple[type[Base], str], tuple[type[Base], str, bool]] = {
    (Account, "AccountIdentity"): (AccountIdentity, "Account", False),
    (Account, "AccountProfile"): (AccountProfile, "Account", False),
    (Account, "AccountOnRole"): (AccountOnRole, "Account", True),
    (Account, "LastAccountRole"): (AccountRole, "accounts", False),
    (AccountRole, "AccountOnRole"): (AccountOnRole, "AccountRole", True),
    (AccountRole, "accounts"): (Account, "LastAccountRole", True),
    (AccountOnRole, "AccountRole"): (AccountRole, "AccountOnRole", False),
    (AccountOnRole, "Account"): (Account, "AccountOnRole", False),
    (AccountIdentity, "Account"): (Account, "AccountIdentity", False),
    (AccountProfile, "Account"): (Account, "AccountProfile", False),
}


def test_the_mappers_configure_without_an_ambiguous_join() -> None:
    configure_mappers()


def test_each_model_has_exactly_the_prisma_relationships() -> None:
    configure_mappers()

    actual = {
        (cls, name)
        for cls in MODELS
        for name in (prop.key for prop in inspect(cls).relationships)
    }

    assert actual == set(RELATIONSHIPS)


@pytest.mark.parametrize(
    ("owner", "name"),
    RELATIONSHIPS,
    ids=[f"{o.__name__}.{n}" for o, n in RELATIONSHIPS],
)
def test_a_relationship_points_at_its_target_and_back(
    owner: type[Base], name: str
) -> None:
    configure_mappers()
    target, back, is_list = RELATIONSHIPS[(owner, name)]

    relationship = inspect(owner).relationships[name]

    assert (
        relationship.mapper.class_,
        relationship.back_populates,
        relationship.uselist,
    ) == (
        target,
        back,
        is_list,
    )


def test_linking_one_side_fills_the_other_side_in_memory() -> None:
    account = Account()
    identity = AccountIdentity(Account=account)
    profile = AccountProfile(Account=account)
    role = AccountRole(type=AccountRoleType.CUSTOMER)
    link = AccountOnRole(Account=account, AccountRole=role)
    account.LastAccountRole = role

    assert account.AccountIdentity is identity
    assert account.AccountProfile is profile
    assert account.AccountOnRole == [link]
    assert role.AccountOnRole == [link]
    assert role.accounts == [account]
