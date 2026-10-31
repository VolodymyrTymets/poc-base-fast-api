"""FileType and table File. Tasks: 2.3."""

import enum
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Index, Integer, LargeBinary, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, IdMixin, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.account import Account
    from app.models.account_profile import AccountProfile


class FileType(enum.StrEnum):
    IMG = "IMG"
    VIDEO = "VIDEO"


# The Node schema declares this type but no column uses it, so it is tied to the metadata
# directly: without that, create_all (and the Alembic revision of 2.4) would never emit it
# and the Node enum would be missing from the database. Nothing may rely on it yet.
FILE_TYPE = Enum(FileType, name="FileType", metadata=Base.metadata)


class File(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "File"

    name: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column("mimeType", Text)
    size: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    created_by_id: Mapped[str] = mapped_column(
        "createdById",
        Text,
        ForeignKey("Account.id", ondelete="RESTRICT", onupdate="CASCADE"),
    )
    # The bytes live in Postgres (ADR-0009). Not deferred: an async session cannot lazy-load a
    # column, so callers that list files choose their columns with `load_only` instead.
    content: Mapped[bytes | None] = mapped_column(LargeBinary)

    created_by: Mapped[Account] = relationship(back_populates="files")
    account_profiles: Mapped[list[AccountProfile]] = relationship(
        back_populates="avatar"
    )


# Declared after the class: the descending index needs the mapped column.
Index("File_createdAt_mimeType_idx", File.created_at.desc(), File.mime_type)
