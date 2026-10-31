"""Notification and NotificationRecipient against the DDL of ../poc-base (init migration). No database.

Their foreign keys are asserted in test_account_models.py, which owns the closed set of foreign keys on Base.
"""

from typing import Any

import pytest
from sqlalchemy import Column, Table, inspect
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import CreateTable, DefaultClause

from app.core.db import Base
from app.models import Account, Notification, NotificationRecipient

POSTGRES = create_async_engine("postgresql+asyncpg://").dialect

TS = "TIMESTAMP(3) WITHOUT TIME ZONE"

# column name -> (compiled type, nullable, server default). Column order is not compared.
COLUMNS: dict[str, dict[str, tuple[str, bool, str | None]]] = {
    "Notification": {
        "id": ("TEXT", False, None),
        "createdAt": (TS, False, "CURRENT_TIMESTAMP"),
        "updatedAt": (TS, True, None),
        "deleted": ("BOOLEAN", False, "false"),
        "message": ("TEXT", False, None),
        "type": ("TEXT", False, None),
    },
    "NotificationRecipient": {
        "notificationId": ("TEXT", False, None),
        "accountId": ("TEXT", False, None),
        "deleted": ("BOOLEAN", False, "false"),
    },
}

PRIMARY_KEYS = {
    "Notification": ("Notification_pkey", ["id"]),
    "NotificationRecipient": (
        "NotificationRecipient_pkey",
        ["notificationId", "accountId"],
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
def test_a_table_has_no_index_and_no_unique_beyond_its_key(name: str) -> None:
    uniques = [
        c for c in table(name).constraints if type(c).__name__ == "UniqueConstraint"
    ]

    assert list(table(name).indexes) == []
    assert uniques == []


@pytest.mark.parametrize("name", COLUMNS)
def test_create_table_compiles_with_quoted_mixed_case_names(name: str) -> None:
    sql = str(CreateTable(table(name)).compile(dialect=POSTGRES))

    assert sql.startswith(f'\nCREATE TABLE "{name}" (')


# (class, relationship name) -> (target class, name on the other side, is a list)
RELATIONSHIPS: dict[tuple[type[Base], str], tuple[type[Base], str, bool]] = {
    (Notification, "notification_recipients"): (
        NotificationRecipient,
        "notification",
        True,
    ),
    (NotificationRecipient, "notification"): (
        Notification,
        "notification_recipients",
        False,
    ),
    (NotificationRecipient, "account"): (Account, "notification_recipients", False),
}


def test_each_notification_model_has_exactly_the_expected_relationships() -> None:
    configure_mappers()

    models: list[type[Base]] = [Notification, NotificationRecipient]

    actual = {(cls, prop.key) for cls in models for prop in inspect(cls).relationships}

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
    ) == (target, back, is_list)


def test_linking_a_recipient_to_a_notification_and_account_fills_both_sides() -> None:
    configure_mappers()
    notification = Notification(message="hi", type="WELCOME")
    account = Account()

    recipient = NotificationRecipient(notification=notification, account=account)

    assert (
        notification.notification_recipients,
        account.notification_recipients,
    ) == ([recipient], [recipient])
