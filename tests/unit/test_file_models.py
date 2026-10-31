"""The File table and FileType against the final DDL of ../poc-base (init, kan_6 x2). No database.

The foreign keys of File and the one that points at it are asserted in test_account_models.py, which owns
the closed set of foreign keys on Base.
"""

from typing import Any

import pytest
from sqlalchemy import Column, Table, create_mock_engine, inspect
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import CreateIndex, CreateTable, DefaultClause

from app.core.db import Base
from app.models import Account, AccountProfile, File, FileType

POSTGRES = create_async_engine("postgresql+asyncpg://").dialect

TS = "TIMESTAMP(3) WITHOUT TIME ZONE"

# column name -> (compiled type, nullable, server default). `key` and `status` are gone and
# `content` was added by the later migrations; column order is not compared.
FILE_COLUMNS: dict[str, tuple[str, bool, str | None]] = {
    "id": ("TEXT", False, None),
    "createdAt": (TS, False, "CURRENT_TIMESTAMP"),
    "updatedAt": (TS, True, None),
    "deleted": ("BOOLEAN", False, "false"),
    "name": ("TEXT", True, None),
    "mimeType": ("TEXT", True, None),
    "size": ("INTEGER", False, "0"),
    "createdById": ("TEXT", False, None),
    "content": ("BYTEA", True, None),
}


def file_table() -> Table:
    return Base.metadata.tables["File"]


def server_default(column: Column[Any]) -> str | None:
    default = column.server_default
    if default is None:
        return None
    assert isinstance(default, DefaultClause), f"{column.name}: unexpected {default!r}"
    return str(default.arg)


def test_file_has_the_prisma_columns_types_nullability_and_defaults() -> None:
    actual = {
        column.name: (
            column.type.compile(dialect=POSTGRES),
            column.nullable,
            server_default(column),
        )
        for column in file_table().columns
    }

    assert actual == FILE_COLUMNS


def test_file_has_the_prisma_primary_key() -> None:
    primary_key = file_table().primary_key

    assert (primary_key.name, [c.name for c in primary_key.columns]) == (
        "File_pkey",
        ["id"],
    )


def test_file_has_exactly_the_created_at_mime_type_index_and_no_unique() -> None:
    indexes = {
        index.name: [column.name for column in index.columns]
        for index in file_table().indexes
    }
    uniques = [
        c for c in file_table().constraints if type(c).__name__ == "UniqueConstraint"
    ]

    assert indexes == {"File_createdAt_mimeType_idx": ["createdAt", "mimeType"]}
    assert uniques == []


def test_the_file_index_sorts_created_at_descending() -> None:
    (index,) = file_table().indexes

    assert 'ON "File" ("createdAt" DESC, "mimeType")' in str(
        CreateIndex(index).compile(dialect=POSTGRES)
    )


def test_create_table_compiles_with_quoted_mixed_case_names() -> None:
    sql = str(CreateTable(file_table()).compile(dialect=POSTGRES))

    assert sql.startswith('\nCREATE TABLE "File" (')


def test_create_all_emits_the_file_type_although_no_column_uses_it() -> None:
    statements: list[str] = []
    engine = create_mock_engine(
        "postgresql+asyncpg://",
        lambda sql, *_, **__: statements.append(str(sql.compile(dialect=POSTGRES))),
    )

    Base.metadata.create_all(engine, checkfirst=False)

    assert list(FileType) == ["IMG", "VIDEO"]
    assert any(
        "CREATE TYPE \"FileType\" AS ENUM ('IMG', 'VIDEO')" in sql for sql in statements
    )


# (class, relationship name) -> (target class, name on the other side, is a list)
FILE_RELATIONSHIPS: dict[tuple[type[Base], str], tuple[type[Base], str, bool]] = {
    (File, "created_by"): (Account, "files", False),
    (File, "account_profiles"): (AccountProfile, "avatar", True),
}


def test_file_has_exactly_its_two_relationships() -> None:
    configure_mappers()

    assert {prop.key for prop in inspect(File).relationships} == {
        "created_by",
        "account_profiles",
    }


@pytest.mark.parametrize(
    ("owner", "name"),
    FILE_RELATIONSHIPS,
    ids=[f"{o.__name__}.{n}" for o, n in FILE_RELATIONSHIPS],
)
def test_a_file_relationship_points_at_its_target_and_back(
    owner: type[Base], name: str
) -> None:
    configure_mappers()
    target, back, is_list = FILE_RELATIONSHIPS[(owner, name)]

    relationship = inspect(owner).relationships[name]

    assert (
        relationship.mapper.class_,
        relationship.back_populates,
        relationship.uselist,
    ) == (target, back, is_list)


def test_linking_a_file_to_a_profile_fills_both_sides_in_memory() -> None:
    configure_mappers()
    file = File(name="a.png")
    profile = AccountProfile(avatar=file)

    assert file.account_profiles == [profile]


def test_the_tables_can_be_ordered_so_file_comes_before_the_profile_that_points_at_it() -> (
    None
):
    order = [t.name for t in Base.metadata.sorted_tables]

    assert order.index("Account") < order.index("File") < order.index("AccountProfile")
