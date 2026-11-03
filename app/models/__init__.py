"""Models: SQLAlchemy tables, built on the declarative base from core/db.py. Tasks: 2.2, 2.3, 5.1."""

# Importing the modules registers their tables on Base.metadata, which Alembic (2.4) reads.
from app.models.account import Account, AccountIdentity
from app.models.account_profile import AccountProfile
from app.models.account_role import AccountOnRole, AccountRole, AccountRoleType
from app.models.file import File, FileType
from app.models.notification import Notification, NotificationRecipient
from app.models.system import DeletedHistory, SeedHistory

__all__ = [
    "Account",
    "AccountIdentity",
    "AccountOnRole",
    "AccountProfile",
    "AccountRole",
    "AccountRoleType",
    "DeletedHistory",
    "File",
    "FileType",
    "Notification",
    "NotificationRecipient",
    "SeedHistory",
]
