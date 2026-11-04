"""The service providers of app/dependencies.py over HTTP, on a real database. Issue: I.9, ADR-0025.

A route never builds a service, so a request shares one session and a test can replace a service.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Annotated

from fastapi import Depends, FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from utils.client import running_client
from utils.jwt import ACCESS_KEY, REFRESH_KEY
from utils.queue import EnqueuedJob, FakeQueue

from app.config import Settings
from app.core.db import create_session_factory, get_session
from app.core.security import TokenClaims, TokenType, issue_token
from app.dependencies import (
    get_account_role_service,
    get_account_service,
    get_notifier_service,
    get_otp_service,
    get_queue,
    require_roles,
)
from app.main import create_app
from app.models import Account, AccountProfile, AccountRoleType
from app.services.account_role import AccountRoleService
from app.services.notifier import NotifierService, NotifierType
from app.services.otp import OtpService

CUSTOMER = AccountRoleType.CUSTOMER
# Tokens carry a UUID subject; no such account exists, only the fake service knows it.
FAKE_ID = "33333333-3333-4333-8333-333333333333"


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
    token = issue_token(settings, account_id, TokenType.ACCESS)
    return {"Authorization": f"Bearer {token}"}


async def new_account(db_engine: AsyncEngine) -> str:
    async with create_session_factory(db_engine)() as session, session.begin():
        account = Account(last_login_at=datetime.now(UTC).replace(tzinfo=None))
        session.add(account)
        await session.flush()
        return account.id


async def test_a_provider_shares_the_session_the_route_commits(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    # The service flushes through its provider and the route commits through get_session: the row is
    # visible on a separate connection only if both used one session.
    account_id = await new_account(db_engine)
    app = make_app(module_database_url)

    @app.post("/api/v1/_grant")
    async def grant(
        service: Annotated[AccountRoleService, Depends(get_account_role_service)],
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> dict[str, str]:
        await service.add_account_to_role(account_id, CUSTOMER)
        await session.commit()
        return {"ok": "true"}

    async with running_client(app) as client:
        response = await client.post("/api/v1/_grant")

    assert response.status_code == 200
    async with create_session_factory(db_engine)() as session:
        assert await AccountRoleService(session).get_account_roles(account_id) == [
            CUSTOMER
        ]


async def test_a_test_can_replace_the_role_service_behind_require_roles(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    account_id = await new_account(db_engine)
    app = make_app(module_database_url)

    @app.get("/api/v1/_customer")
    async def customer_only(
        claims: Annotated[TokenClaims, Depends(require_roles(CUSTOMER))],
    ) -> dict[str, str]:
        return {"id": claims.account_id}

    async def roles_of_anyone(account_id: str) -> list[AccountRoleType]:
        return [CUSTOMER]

    app.dependency_overrides[get_account_role_service] = lambda: SimpleNamespace(
        get_account_roles=roles_of_anyone
    )

    async with running_client(app) as client:
        response = await client.get("/api/v1/_customer", headers=token_for(account_id))

    # The account holds no role in the database: only the fake lets it through.
    assert response.status_code == 200
    assert response.json() == {"id": account_id}


async def test_a_test_can_replace_the_account_service_behind_a_real_route(
    module_database_url: str,
) -> None:
    app = make_app(module_database_url)
    created = datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None)

    async def fake_account(account_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            id=account_id, created_at=created, updated_at=None, profile=None
        )

    app.dependency_overrides[get_account_service] = lambda: SimpleNamespace(
        get_by_id=fake_account
    )

    async with running_client(app) as client:
        response = await client.get("/api/v1/account", headers=token_for(FAKE_ID))

    assert response.status_code == 200
    assert response.json()["id"] == FAKE_ID


async def test_the_notifier_provider_reads_through_the_request_and_queues_on_the_app_queue(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    # The profile is committed on another connection: the notifier finds it through the profile service of
    # the request's session, and the job goes to whatever `get_queue` gives (a recording queue here).
    async with create_session_factory(db_engine)() as session, session.begin():
        account = Account(last_login_at=datetime.now(UTC).replace(tzinfo=None))
        session.add(account)
        await session.flush()
        account_id = account.id
        session.add(AccountProfile(account_id=account_id, phone_number="+380000000001"))
    app = make_app(module_database_url)
    queue = FakeQueue()
    app.dependency_overrides[get_queue] = lambda: queue

    @app.post("/api/v1/_notify")
    async def notify(
        service: Annotated[NotifierService, Depends(get_notifier_service)],
    ) -> dict[str, str]:
        await service.notify_about_totp_code(account_id, "482913", [NotifierType.ALL])
        return {"ok": "true"}

    async with running_client(app) as client:
        response = await client.post("/api/v1/_notify")

    assert response.status_code == 200
    assert queue.jobs == [
        EnqueuedJob("send_totp_code", ("+380000000001", "482913"), {})
    ]


async def test_a_test_can_replace_the_notifier_service(
    module_database_url: str,
) -> None:
    app = make_app(module_database_url)
    seen: list[str] = []

    async def notify(account_id: str, code: str, types: object) -> None:
        seen.append(account_id)

    app.dependency_overrides[get_notifier_service] = lambda: SimpleNamespace(
        notify_about_totp_code=notify
    )

    @app.post("/api/v1/_notify")
    async def route(
        service: Annotated[NotifierService, Depends(get_notifier_service)],
    ) -> dict[str, str]:
        await service.notify_about_totp_code(FAKE_ID, "1", [NotifierType.ALL])
        return {"ok": "true"}

    async with running_client(app) as client:
        response = await client.post("/api/v1/_notify")

    assert (response.status_code, seen) == (200, [FAKE_ID])


async def test_a_test_can_replace_the_otp_service(module_database_url: str) -> None:
    app = make_app(module_database_url)
    seen: list[str] = []

    async def issue(phone_number: str) -> None:
        seen.append(phone_number)

    app.dependency_overrides[get_otp_service] = lambda: SimpleNamespace(issue=issue)

    @app.post("/api/v1/_otp")
    async def route(
        service: Annotated[OtpService, Depends(get_otp_service)],
    ) -> dict[str, str]:
        await service.issue("+380000000001")
        return {"ok": "true"}

    async with running_client(app) as client:
        response = await client.post("/api/v1/_otp")

    assert (response.status_code, seen) == (200, ["+380000000001"])
