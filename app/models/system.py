"""Tables DeletedHistory and Migration. Tasks: 2.3."""

from datetime import datetime

from sqlalchemy import Index, Text, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, utc_now

# Neither table has a `deleted` column in the Node schema: they are bookkeeping tables, not
# domain tables, so SoftDeleteMixin is not used and rule P6 (no hard DELETE on domain tables)
# does not apply. Nothing writes to them yet.


class DeletedHistory(IdMixin, Base):
    __tablename__ = "DeletedHistory"

    relation_id: Mapped[str] = mapped_column("relationId", Text)
    # A flag, not a timestamp, despite the name; the column keeps the Node name for schema
    # parity (ADR-0004), as `dataOfBirth` does.
    deleted_at: Mapped[bool] = mapped_column("deletedAt")
    deleted_by: Mapped[str | None] = mapped_column("deletedBy", Text)

    __table_args__ = (Index("DeletedHistory_relationId_idx", "relationId"),)


class Migration(IdMixin, Base):
    """A data migration run by the app (not an Alembic revision, which lives in `alembic_version`)."""

    __tablename__ = "Migration"

    name: Mapped[str] = mapped_column(Text)
    successful: Mapped[bool] = mapped_column(
        default=False, server_default=text("false")
    )
    result: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    # Nullable here, unlike TimestampMixin.created_at, because the Node column is
    # `TIMESTAMP(3) DEFAULT CURRENT_TIMESTAMP` without NOT NULL; hence declared by hand.
    created_at: Mapped[datetime | None] = mapped_column(
        "createdAt",
        TIMESTAMP(precision=3),
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        "updatedAt", TIMESTAMP(precision=3), default=utc_now, onupdate=utc_now
    )
