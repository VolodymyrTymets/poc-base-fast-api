import pytest
from sqlalchemy import ForeignKey, Index, MetaData
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.schema import CreateIndex, CreateTable

from app.core.db import (
    NAMING_CONVENTION,
    Base,
    IdMixin,
    SoftDeleteMixin,
    TimestampMixin,
    new_id,
    utc_now,
)

# The dialect the DDL is compiled for; an engine opens no connection until it is used.
POSTGRES = create_async_engine("postgresql+asyncpg://").dialect


# A scratch base keeps the real Base.metadata empty: Alembic (2.4) diffs that one.
class ScratchBase(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Thing(IdMixin, TimestampMixin, SoftDeleteMixin, ScratchBase):
    __tablename__ = "Thing"
    code: Mapped[str] = mapped_column(unique=True)
    __table_args__ = (Index(None, "code", "deleted"),)


class Part(ScratchBase):
    __tablename__ = "Part"
    id: Mapped[int] = mapped_column(primary_key=True)
    thing_id: Mapped[str] = mapped_column("thingId", ForeignKey(Thing.id))


class OnlyId(IdMixin, ScratchBase):
    __tablename__ = "OnlyId"


class OnlyTimestamps(TimestampMixin, ScratchBase):
    __tablename__ = "OnlyTimestamps"
    key: Mapped[int] = mapped_column(primary_key=True)


class OnlySoftDelete(SoftDeleteMixin, ScratchBase):
    __tablename__ = "OnlySoftDelete"
    key: Mapped[int] = mapped_column(primary_key=True)


def create_table_sql(name: str) -> str:
    table = ScratchBase.metadata.tables[name]
    return str(CreateTable(table).compile(dialect=POSTGRES))


def test_the_real_base_has_no_tables_until_the_models_land() -> None:
    assert dict(Base.metadata.tables) == {}


def test_constraints_and_indexes_are_named_the_way_prisma_names_them() -> None:
    thing = ScratchBase.metadata.tables["Thing"]
    part = ScratchBase.metadata.tables["Part"]

    assert {constraint.name for constraint in thing.constraints} == {
        "Thing_pkey",
        "Thing_code_key",
    }
    assert {index.name for index in thing.indexes} == {"Thing_code_deleted_idx"}
    assert {constraint.name for constraint in part.constraints} == {
        "Part_pkey",
        "Part_thingId_fkey",
    }


def test_a_mixed_case_index_is_created_quoted() -> None:
    (index,) = ScratchBase.metadata.tables["Thing"].indexes

    sql = str(CreateIndex(index).compile(dialect=POSTGRES))

    assert sql == 'CREATE INDEX "Thing_code_deleted_idx" ON "Thing" (code, deleted)'


@pytest.mark.parametrize(
    "fragment",
    [
        'CREATE TABLE "Thing"',
        "id TEXT NOT NULL",
        '"createdAt" TIMESTAMP(3) WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL',
        '"updatedAt" TIMESTAMP(3) WITHOUT TIME ZONE,',
        "deleted BOOLEAN DEFAULT false NOT NULL",
        'CONSTRAINT "Thing_pkey" PRIMARY KEY (id)',
    ],
    ids=["table", "id", "createdAt", "updatedAt-nullable", "deleted", "primary-key"],
)
def test_the_mixins_emit_the_prisma_column_shapes(fragment: str) -> None:
    assert fragment in create_table_sql("Thing")


@pytest.mark.parametrize(
    ("table", "columns"),
    [
        ("OnlyId", {"id"}),
        ("OnlyTimestamps", {"key", "createdAt", "updatedAt"}),
        ("OnlySoftDelete", {"key", "deleted"}),
    ],
)
def test_each_mixin_works_alone(table: str, columns: set[str]) -> None:
    assert set(ScratchBase.metadata.tables[table].columns.keys()) == columns


def test_new_ids_are_distinct_uuid_strings() -> None:
    first, second = new_id(), new_id()

    assert first != second
    assert len(first) == 36


def test_utc_now_is_naive_because_the_columns_have_no_time_zone() -> None:
    assert utc_now().tzinfo is None
