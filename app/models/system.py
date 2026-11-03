"""Tables DeletedHistory (task 2.3) and SeedHistory (task 5.1).

The Node schema's `Migration` table is not mapped: Alembic's own `alembic_version` table records which
revisions ran (ADR-0018). `SeedHistory` is a different table: it records which seed items ran (not schema
revisions), and exists only in this base, from revision `0002_seed_history`.
"""

from datetime import datetime

from sqlalchemy import Index, Text, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin

# No `deleted` column in the Node schema: this is a bookkeeping table, not a domain table, so
# SoftDeleteMixin is not used and rule P6 (no hard DELETE on domain tables) does not apply.
# Nothing writes to it yet.


class DeletedHistory(IdMixin, Base):
    __tablename__ = "DeletedHistory"

    relation_id: Mapped[str] = mapped_column("relationId", Text)
    # A flag, not a timestamp, despite the name; the column keeps the Node name for schema
    # parity (ADR-0004), as `dataOfBirth` does.
    deleted_at: Mapped[bool] = mapped_column("deletedAt")
    deleted_by: Mapped[str | None] = mapped_column("deletedBy", Text)

    __table_args__ = (Index("DeletedHistory_relationId_idx", "relationId"),)


class SeedHistory(IdMixin, Base):
    """One row per seed item, updated in place when it is retried (`name` is unique).

    Bookkeeping like `DeletedHistory`: no `deleted` column, so rule P6 does not apply to it.
    """

    __tablename__ = "SeedHistory"

    name: Mapped[str] = mapped_column(Text)
    successful: Mapped[bool] = mapped_column(
        default=False, server_default=text("false")
    )
    # The error of a failed run (class and message only); null once the item succeeds.
    result: Mapped[str | None] = mapped_column(Text)
    # Not TimestampMixin: the table has no `updatedAt`.
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP(precision=3),
        server_default=text("CURRENT_TIMESTAMP"),
    )

    # A unique index named as Prisma would, like `AccountRole_type_key`.
    __table_args__ = (Index("SeedHistory_name_key", "name", unique=True),)
