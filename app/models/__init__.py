"""Models: SQLAlchemy tables, built on the declarative base from core/db.py. Tasks: 2.2, 2.3."""

# Importing the modules registers their tables on Base.metadata, which Alembic (2.4) reads.
from app.models.account import Account, AccountIdentity
from app.models.account_profile import AccountProfile
from app.models.account_role import AccountOnRole, AccountRole, AccountRoleType

__all__ = [
    "Account",
    "AccountIdentity",
    "AccountOnRole",
    "AccountProfile",
    "AccountRole",
    "AccountRoleType",
]
