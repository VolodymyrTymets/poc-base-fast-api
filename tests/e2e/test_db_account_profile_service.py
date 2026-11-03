"""AccountProfileService on a real Postgres (the template database holds the seeded roles). Task: 5.4."""

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.errors import EmailAlreadyRegisteredError, ForbiddenError, NotFoundError
from app.models import Account, AccountProfile, File
from app.schemas.account_profile import UpdateAccountProfileInput
from app.services.account import AccountService
from app.services.account_profile import AccountProfileService
from app.services.file_assert import FileAssertService

MISSING_ID = "00000000-0000-4000-8000-000000000000"


def service(session: AsyncSession) -> AccountProfileService:
    settings = Settings(database_url=None)
    return AccountProfileService(session, FileAssertService(session, settings))


def changes(**fields: object) -> UpdateAccountProfileInput:
    # Built from the wire names, as a request body is.
    return UpdateAccountProfileInput.model_validate(fields)


async def make_account(session: AsyncSession, email: str) -> str:
    account = await AccountService(session).create_password_account(email, "h", "s")
    account_id = account.id
    session.expunge_all()
    return account_id


async def make_file(session: AsyncSession, owner_id: str) -> str:
    file = File(name="a.png", mime_type="image/png", size=1, created_by_id=owner_id)
    session.add(file)
    await session.flush()
    file_id = file.id
    session.expunge_all()
    return file_id


async def stored(session: AsyncSession, account_id: str) -> AccountProfile:
    session.expunge_all()
    return (
        await session.scalars(
            select(AccountProfile).where(AccountProfile.account_id == account_id)
        )
    ).one()


async def test_the_sent_fields_are_updated_and_the_profile_is_returned(
    db_session: AsyncSession,
) -> None:
    account_id = await make_account(db_session, "a1@example.com")

    profile = await service(db_session).update(
        account_id,
        account_id,
        changes(firstName="Jane", lastName="Doe", dataOfBirth="1990-01-02"),
    )

    row = await stored(db_session, account_id)
    assert profile.account_id == account_id
    assert (row.first_name, row.last_name, row.date_of_birth) == (
        "Jane",
        "Doe",
        "1990-01-02",
    )


async def test_a_field_that_is_not_sent_is_left_alone(db_session: AsyncSession) -> None:
    account_id = await make_account(db_session, "a2@example.com")
    await service(db_session).update(
        account_id, account_id, changes(firstName="Original")
    )

    await service(db_session).update(account_id, account_id, changes(lastName="New"))

    row = await stored(db_session, account_id)
    assert (row.first_name, row.last_name, row.email) == (
        "Original",
        "New",
        "a2@example.com",
    )


async def test_an_explicit_null_clears_a_field(db_session: AsyncSession) -> None:
    account_id = await make_account(db_session, "a3@example.com")
    await service(db_session).update(account_id, account_id, changes(middleName="Mid"))

    await service(db_session).update(account_id, account_id, changes(middleName=None))

    assert (await stored(db_session, account_id)).middle_name is None


async def test_an_empty_update_changes_nothing(db_session: AsyncSession) -> None:
    account_id = await make_account(db_session, "a4@example.com")

    profile = await service(db_session).update(account_id, account_id, changes())

    assert profile.email == "a4@example.com"


async def test_the_email_is_stored_normalised(db_session: AsyncSession) -> None:
    account_id = await make_account(db_session, "a5@example.com")

    await service(db_session).update(
        account_id, account_id, changes(email="New.Name@Example.COM")
    )

    assert (await stored(db_session, account_id)).email == "new.name@example.com"


async def test_the_own_email_again_is_not_a_conflict(db_session: AsyncSession) -> None:
    account_id = await make_account(db_session, "a6@example.com")

    profile = await service(db_session).update(
        account_id, account_id, changes(email="A6@example.com")
    )

    assert profile.email == "a6@example.com"


async def test_an_email_another_account_has_is_refused_in_any_case(
    db_session: AsyncSession,
) -> None:
    await make_account(db_session, "taken@example.com")
    account_id = await make_account(db_session, "b1@example.com")

    with pytest.raises(EmailAlreadyRegisteredError):
        await service(db_session).update(
            account_id, account_id, changes(email="TAKEN@example.com")
        )

    # The session is still usable and the profile is as it was.
    assert (await stored(db_session, account_id)).email == "b1@example.com"


async def test_an_email_held_by_a_soft_deleted_account_is_still_refused(
    db_session: AsyncSession,
) -> None:
    gone_id = await make_account(db_session, "gone@example.com")
    await db_session.execute(
        update(Account).where(Account.id == gone_id).values(deleted=True)
    )
    account_id = await make_account(db_session, "b2@example.com")

    with pytest.raises(EmailAlreadyRegisteredError):
        await service(db_session).update(
            account_id, account_id, changes(email="gone@example.com")
        )


async def test_an_email_held_by_a_soft_deleted_profile_is_still_refused(
    db_session: AsyncSession,
) -> None:
    other_id = await make_account(db_session, "gone2@example.com")
    await db_session.execute(
        update(AccountProfile)
        .where(AccountProfile.account_id == other_id)
        .values(deleted=True)
    )
    account_id = await make_account(db_session, "b3@example.com")

    with pytest.raises(EmailAlreadyRegisteredError):
        await service(db_session).update(
            account_id, account_id, changes(email="gone2@example.com")
        )


async def test_another_caller_is_forbidden_and_nothing_is_written(
    db_session: AsyncSession,
) -> None:
    owner_id = await make_account(db_session, "c1@example.com")
    caller_id = await make_account(db_session, "c2@example.com")

    with pytest.raises(ForbiddenError):
        await service(db_session).update(caller_id, owner_id, changes(firstName="X"))

    assert (await stored(db_session, owner_id)).first_name is None


async def test_the_ownership_check_runs_before_anything_is_read(
    db_session: AsyncSession,
) -> None:
    # A missing profile would be a 404; a caller who is not the owner must get the 403 first.
    caller_id = await make_account(db_session, "c3@example.com")

    with pytest.raises(ForbiddenError):
        await service(db_session).update(caller_id, MISSING_ID, changes())


async def test_an_avatar_the_caller_owns_is_accepted(db_session: AsyncSession) -> None:
    account_id = await make_account(db_session, "d1@example.com")
    file_id = await make_file(db_session, account_id)

    await service(db_session).update(account_id, account_id, changes(avatarId=file_id))

    assert (await stored(db_session, account_id)).avatar_id == file_id


async def test_an_avatar_of_another_account_is_forbidden_and_nothing_is_written(
    db_session: AsyncSession,
) -> None:
    owner_id = await make_account(db_session, "d2@example.com")
    account_id = await make_account(db_session, "d3@example.com")
    file_id = await make_file(db_session, owner_id)

    with pytest.raises(ForbiddenError):
        await service(db_session).update(
            account_id, account_id, changes(avatarId=file_id, firstName="X")
        )

    row = await stored(db_session, account_id)
    assert (row.avatar_id, row.first_name) == (None, None)


@pytest.mark.parametrize("case", ["unknown", "soft-deleted"])
async def test_an_unknown_or_soft_deleted_avatar_is_forbidden(
    db_session: AsyncSession, case: str
) -> None:
    account_id = await make_account(db_session, f"d4-{case}@example.com")
    file_id = await make_file(db_session, account_id)
    if case == "soft-deleted":
        await db_session.execute(
            update(File).where(File.id == file_id).values(deleted=True)
        )
    else:
        file_id = MISSING_ID

    with pytest.raises(ForbiddenError):
        await service(db_session).update(
            account_id, account_id, changes(avatarId=file_id)
        )


async def test_a_null_avatar_removes_it(db_session: AsyncSession) -> None:
    account_id = await make_account(db_session, "d5@example.com")
    file_id = await make_file(db_session, account_id)
    await service(db_session).update(account_id, account_id, changes(avatarId=file_id))

    await service(db_session).update(account_id, account_id, changes(avatarId=None))

    assert (await stored(db_session, account_id)).avatar_id is None


async def test_an_account_with_no_profile_is_not_found(
    db_session: AsyncSession,
) -> None:
    account_id = await make_account(db_session, "e1@example.com")
    await db_session.execute(
        update(AccountProfile)
        .where(AccountProfile.account_id == account_id)
        .values(deleted=True)
    )

    with pytest.raises(NotFoundError):
        await service(db_session).update(account_id, account_id, changes())


async def test_a_soft_deleted_account_is_not_found(db_session: AsyncSession) -> None:
    account_id = await make_account(db_session, "e2@example.com")
    await db_session.execute(
        update(Account).where(Account.id == account_id).values(deleted=True)
    )

    with pytest.raises(NotFoundError):
        await service(db_session).update(account_id, account_id, changes())


async def test_get_by_account_id_gives_the_live_profile_or_none(
    db_session: AsyncSession,
) -> None:
    account_id = await make_account(db_session, "f1@example.com")

    found = await service(db_session).get_by_account_id(account_id)
    missing = await service(db_session).get_by_account_id(MISSING_ID)

    assert found is not None
    assert found.email == "f1@example.com"
    assert missing is None


async def test_a_failed_update_leaves_the_session_usable(
    db_session: AsyncSession,
) -> None:
    await make_account(db_session, "taken2@example.com")
    account_id = await make_account(db_session, "g1@example.com")
    with pytest.raises(EmailAlreadyRegisteredError):
        await service(db_session).update(
            account_id, account_id, changes(email="taken2@example.com")
        )

    count = await db_session.scalar(select(func.count()).select_from(AccountProfile))

    assert count is not None
    assert count >= 2
