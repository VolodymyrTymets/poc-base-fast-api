"""Creates the sample customer accounts. Ports the Node `InitCustomerMigration`. Task: 5.5.

Development environments only (the registry). Differences from Node, on purpose: it runs although the admin account exists
(Node's `account.count() === 0` was false after the admin seed, so the customers were never created) and creates only the
sample phones that have no account yet; `SSN` is gone (ADR-0015) and so is the `password` field, which Node never read: the
customers have no password identity and sign in by OTP; the phones and emails are fictional (555-0100 range, `example.com`).
"""

from typing import TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.schemas.account_profile import UpdateAccountProfileInput
from app.services.account import AccountService
from app.services.account_profile import AccountProfileService
from app.services.file_assert import FileAssertService


class CustomerSample(TypedDict):
    phone_number: str
    email: str
    first_name: str
    last_name: str
    middle_name: str
    date_of_birth: str


# 555-0100 to 555-0199 is the NANP range reserved for fiction, so no number belongs to a real person.
CUSTOMERS: list[CustomerSample] = [
    {
        "phone_number": "+12125550101",
        "email": "customer+d1@example.com",
        "first_name": "John",
        "last_name": "Doe",
        "middle_name": "Smith",
        "date_of_birth": "1990-01-01",
    },
    {
        "phone_number": "+12125550102",
        "email": "customer+d2@example.com",
        "first_name": "Jane",
        "last_name": "Doe",
        "middle_name": "Smith",
        "date_of_birth": "1995-05-05",
    },
    {
        "phone_number": "+12125550103",
        "email": "customer+d3@example.com",
        "first_name": "Alice",
        "last_name": "Smith",
        "middle_name": "Johnson",
        "date_of_birth": "1985-10-10",
    },
]


class InitCustomer:
    # The Node name without the `.migration` suffix, like `init.roles`.
    name = "init.customer"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def needs_to_run(self, session: AsyncSession) -> bool:
        accounts = AccountService(session)
        for sample in CUSTOMERS:
            if await accounts.get_by_phone(sample["phone_number"]) is None:
                return True
        return False

    async def run(self, session: AsyncSession) -> None:
        accounts = AccountService(session)
        profiles = AccountProfileService(
            session, FileAssertService(session, self._settings)
        )
        for sample in CUSTOMERS:
            if await accounts.get_by_phone(sample["phone_number"]) is not None:
                continue
            account = await accounts.create_customer(sample["phone_number"])
            await profiles.update(
                account.id,
                account.id,
                # By wire name, as a request body: the field `dataOfBirth` has an explicit alias that a keyword call cannot use.
                UpdateAccountProfileInput.model_validate(
                    {
                        "firstName": sample["first_name"],
                        "lastName": sample["last_name"],
                        "middleName": sample["middle_name"],
                        "email": sample["email"],
                        "dataOfBirth": sample["date_of_birth"],
                    }
                ),
            )
