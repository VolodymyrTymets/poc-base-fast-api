"""Table DeletedHistory. Tasks: 2.3.

The Node schema's `Migration` table is not mapped: Alembic's own `alembic_version` table records which
revisions ran (ADR-0018).
"""

from sqlalchemy import Index, Text
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
