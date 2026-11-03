"""PATCH /api/v1/accounts/{accountId}/profile over HTTP on a real database. Task: 5.4.

Rows are committed through `db_engine` because the request has its own session; they stay for the module,
so every test makes its own accounts and its own emails.
"""

import uuid
from typing import Any

from fastapi import FastAPI
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine
from utils.client import running_client
from utils.jwt import ACCESS_KEY, REFRESH_KEY

from app.config import Settings
from app.core.db import create_session_factory, utc_now
from app.core.security import TokenType, issue_token
from app.main import create_app
from app.models import Account, AccountProfile, File
from app.services.account import AccountService

BEARER = {"WWW-Authenticate": "Bearer"}


def make_app(database_url: str) -> FastAPI:
    return create_app(
        Settings(
            database_url=database_url,
            jwt_secret=ACCESS_KEY,
            jwt_refresh_token_secret=REFRESH_KEY,
        )
    )


def token_for(account_id: str) -> dict[str, str]:
    settings = Settings(jwt_secret=ACCESS_KEY, jwt_refresh_token_secret=REFRESH_KEY)
    return {
        "Authorization": f"Bearer {issue_token(settings, account_id, TokenType.ACCESS)}"
    }


def path(account_id: str) -> str:
    return f"/api/v1/accounts/{account_id}/profile"


def fresh_email() -> str:
    return f"{uuid.uuid4().hex}@example.com"


async def account_with_email(db_engine: AsyncEngine) -> tuple[str, str]:
    email = fresh_email()
    async with create_session_factory(db_engine)() as session, session.begin():
        account = await AccountService(session).create_password_account(email, "h", "s")
        return account.id, email


async def bare_account(db_engine: AsyncEngine) -> str:
    """An account with no role link and no profile."""
    async with create_session_factory(db_engine)() as session, session.begin():
        account = Account(last_login_at=utc_now())
        session.add(account)
        await session.flush()
        return account.id


async def file_of(db_engine: AsyncEngine, owner_id: str) -> str:
    async with create_session_factory(db_engine)() as session, session.begin():
        file = File(name="a.png", mime_type="image/png", size=1, created_by_id=owner_id)
        session.add(file)
        await session.flush()
        return file.id


async def patch(
    database_url: str, account_id: str, caller: str | None, body: dict[str, Any]
) -> Any:
    headers = token_for(caller) if caller else {}
    async with running_client(make_app(database_url)) as client:
        return await client.patch(path(account_id), json=body, headers=headers)


async def test_the_owner_updates_the_profile_and_the_email_is_stored_lowercase(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    account_id, _ = await account_with_email(db_engine)
    new_email = fresh_email()

    response = await patch(
        module_database_url,
        account_id,
        account_id,
        {"firstName": "Jane", "email": new_email.upper()},
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["firstName"], body["email"]) == ("Jane", new_email)
    assert set(body) == {
        "id",
        "phoneNumber",
        "firstName",
        "lastName",
        "middleName",
        "dataOfBirth",
        "email",
        "isPhoneVerified",
    }


async def test_the_change_is_committed_and_visible_in_get_account(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    account_id, _ = await account_with_email(db_engine)
    await patch(module_database_url, account_id, account_id, {"lastName": "Kept"})

    async with running_client(make_app(module_database_url)) as client:
        response = await client.get("/api/v1/account", headers=token_for(account_id))

    assert response.json()["profile"]["lastName"] == "Kept"


async def test_an_update_leaves_unsent_fields_and_an_empty_body_is_a_no_op(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    account_id, email = await account_with_email(db_engine)
    await patch(module_database_url, account_id, account_id, {"firstName": "Jane"})

    response = await patch(module_database_url, account_id, account_id, {})

    assert response.status_code == 200
    assert (response.json()["firstName"], response.json()["email"]) == ("Jane", email)


async def test_no_token_is_unauthorized(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    account_id, _ = await account_with_email(db_engine)

    response = await patch(module_database_url, account_id, None, {"firstName": "X"})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_another_accounts_id_is_forbidden_and_nothing_changes(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    owner_id, _ = await account_with_email(db_engine)
    caller_id, _ = await account_with_email(db_engine)

    response = await patch(module_database_url, owner_id, caller_id, {"firstName": "X"})
    read = await patch(module_database_url, owner_id, owner_id, {})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert read.json()["firstName"] is None


async def test_an_account_with_no_role_is_forbidden(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    account_id = await bare_account(db_engine)

    response = await patch(module_database_url, account_id, account_id, {})

    assert response.status_code == 403


async def test_a_token_of_an_unknown_account_is_forbidden(
    module_database_url: str,
) -> None:
    unknown = str(uuid.uuid4())

    response = await patch(module_database_url, unknown, unknown, {})

    assert response.status_code == 403


async def test_an_account_with_a_role_but_no_live_profile_is_not_found(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    account_id, _ = await account_with_email(db_engine)
    async with create_session_factory(db_engine)() as session, session.begin():
        await session.execute(
            update(AccountProfile)
            .where(AccountProfile.account_id == account_id)
            .values(deleted=True)
        )

    response = await patch(module_database_url, account_id, account_id, {})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_a_soft_deleted_account_that_keeps_its_role_link_is_not_found(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    # Decided with the owner (Q1 of the spec): 404, not 401. A uniform 401 for deleted accounts is a separate change.
    account_id, _ = await account_with_email(db_engine)
    async with create_session_factory(db_engine)() as session, session.begin():
        await session.execute(
            update(Account).where(Account.id == account_id).values(deleted=True)
        )

    response = await patch(module_database_url, account_id, account_id, {})

    assert response.status_code == 404


async def test_a_duplicate_email_in_another_case_is_a_conflict_and_changes_nothing(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    _, taken = await account_with_email(db_engine)
    account_id, own = await account_with_email(db_engine)

    response = await patch(
        module_database_url, account_id, account_id, {"email": taken.upper()}
    )
    after = await patch(module_database_url, account_id, account_id, {})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"
    assert after.json()["email"] == own


async def test_an_avatar_of_another_account_is_forbidden(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    owner_id, _ = await account_with_email(db_engine)
    account_id, _ = await account_with_email(db_engine)
    file_id = await file_of(db_engine, owner_id)

    response = await patch(
        module_database_url, account_id, account_id, {"avatarId": file_id}
    )

    assert response.status_code == 403


async def test_an_owned_avatar_is_accepted_and_null_removes_it(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    account_id, _ = await account_with_email(db_engine)
    file_id = await file_of(db_engine, account_id)
    set_it = await patch(
        module_database_url, account_id, account_id, {"avatarId": file_id}
    )

    removed = await patch(
        module_database_url, account_id, account_id, {"avatarId": None}
    )

    assert set_it.status_code == 200
    assert removed.status_code == 200


async def test_unknown_keys_and_a_null_email_are_validation_errors(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    account_id, _ = await account_with_email(db_engine)

    ssn = await patch(module_database_url, account_id, account_id, {"SSN": "1"})
    adult = await patch(
        module_database_url, account_id, account_id, {"is18YearOld": True}
    )
    null_email = await patch(
        module_database_url, account_id, account_id, {"email": None}
    )

    assert [r.status_code for r in (ssn, adult, null_email)] == [422, 422, 422]
    assert ssn.json()["error"]["code"] == "VALIDATION_FAILED"
