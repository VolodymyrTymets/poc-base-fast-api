"""The read cache over HTTP, on a real Postgres and a real Redis (task 9.2, ADR-0035). Ports the two flows of the Node `cached-reads.e2e-spec.ts`.

A hit is proved by counting the statements the app's own engine runs: a request served from Redis runs none.
"""

import logging
import uuid
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine
from utils.client import running_client
from utils.jwt import ACCESS_KEY, REFRESH_KEY
from utils.redis import TEST_REDIS_DATABASE
from utils.sql import count_statements

from app.config import Settings
from app.core.cache import ReadCache, RedisCacheStore, cache_key
from app.core.db import create_session_factory
from app.core.security import TokenClaims, TokenType, issue_token
from app.dependencies import require_roles
from app.main import create_app
from app.models import AccountRoleType
from app.services.account import AccountService

ACCOUNT = "/api/v1/account"


def make_app(database_url: str, redis_settings: Settings, **changes: object) -> FastAPI:
    settings = redis_settings.model_copy(
        update={
            "database_url": database_url,
            "jwt_secret": ACCESS_KEY,
            "jwt_refresh_token_secret": REFRESH_KEY,
            "cache_enabled": True,
            **changes,
        }
    )
    return create_app(settings)


def headers_for(account_id: str) -> dict[str, str]:
    settings = Settings(jwt_secret=ACCESS_KEY, jwt_refresh_token_secret=REFRESH_KEY)
    token = issue_token(settings, account_id, TokenType.ACCESS)
    return {"Authorization": f"Bearer {token}"}


async def new_account(db_engine: AsyncEngine) -> tuple[str, str]:
    email = f"{uuid.uuid4().hex}@example.com"
    async with create_session_factory(db_engine)() as session, session.begin():
        account = await AccountService(session).create_password_account(
            email, "secret-hash"
        )
        return account.id, email


def statements_of(app: FastAPI) -> AsyncEngine:
    engine: AsyncEngine = app.state.engine
    return engine


async def test_a_second_read_of_the_account_is_served_from_redis(
    module_database_url: str, redis_settings: Settings, db_engine: AsyncEngine
) -> None:
    # Arrange
    account_id, _ = await new_account(db_engine)
    app = make_app(module_database_url, redis_settings)
    async with running_client(app) as client:
        first = await client.get(ACCOUNT, headers=headers_for(account_id))

        # Act
        with count_statements(statements_of(app)) as statements:
            second = await client.get(ACCOUNT, headers=headers_for(account_id))

    # Assert
    assert (first.status_code, second.status_code, statements) == (200, 200, [])
    assert second.json() == first.json()


async def test_a_hit_returns_the_created_at_as_a_timestamp(
    module_database_url: str, redis_settings: Settings, db_engine: AsyncEngine
) -> None:
    # Arrange
    account_id, _ = await new_account(db_engine)
    app = make_app(module_database_url, redis_settings)
    async with running_client(app) as client:
        first = await client.get(ACCOUNT, headers=headers_for(account_id))

        # Act
        second = await client.get(ACCOUNT, headers=headers_for(account_id))

    # Assert
    assert second.json()["createdAt"] == first.json()["createdAt"]
    assert "T" in second.json()["createdAt"]


async def test_a_profile_update_makes_the_next_read_a_miss_with_the_new_value(
    module_database_url: str, redis_settings: Settings, db_engine: AsyncEngine
) -> None:
    # Arrange
    account_id, _ = await new_account(db_engine)
    app = make_app(module_database_url, redis_settings)
    async with running_client(app) as client:
        await client.get(ACCOUNT, headers=headers_for(account_id))
        await client.patch(
            f"/api/v1/accounts/{account_id}/profile",
            headers=headers_for(account_id),
            json={"firstName": "Ann"},
        )

        # Act
        with count_statements(statements_of(app)) as statements:
            response = await client.get(ACCOUNT, headers=headers_for(account_id))

    # Assert
    assert response.json()["profile"]["firstName"] == "Ann"
    assert len(statements) > 0


async def test_a_rejected_update_leaves_the_cached_account_in_place(
    module_database_url: str, redis_settings: Settings, db_engine: AsyncEngine
) -> None:
    # Arrange
    account_id, _ = await new_account(db_engine)
    _, other_email = await new_account(db_engine)
    app = make_app(module_database_url, redis_settings)
    async with running_client(app) as client:
        await client.get(ACCOUNT, headers=headers_for(account_id))
        rejected = await client.patch(
            f"/api/v1/accounts/{account_id}/profile",
            headers=headers_for(account_id),
            json={"email": other_email},
        )

        # Act
        with count_statements(statements_of(app)) as statements:
            await client.get(ACCOUNT, headers=headers_for(account_id))

    # Assert
    assert (rejected.status_code, statements) == (409, [])


async def test_the_roles_checked_by_require_roles_are_never_served_from_redis(
    module_database_url: str, redis_settings: Settings, db_engine: AsyncEngine
) -> None:
    # Arrange
    account_id, _ = await new_account(db_engine)
    app = make_app(module_database_url, redis_settings)

    @app.get("/api/v1/_customer")
    async def customer_only(
        claims: Annotated[
            TokenClaims, Depends(require_roles(AccountRoleType.CUSTOMER))
        ],
    ) -> dict[str, str]:
        return {"id": claims.account_id}

    async with running_client(app) as client:
        await client.get("/api/v1/_customer", headers=headers_for(account_id))

        # Act
        with count_statements(statements_of(app)) as statements:
            await client.get("/api/v1/_customer", headers=headers_for(account_id))

    # Assert
    assert len(statements) > 0


async def test_a_forged_role_entry_in_redis_does_not_open_an_admin_route(
    module_database_url: str, redis_settings: Settings, db_engine: AsyncEngine
) -> None:
    # Arrange
    account_id, _ = await new_account(db_engine)
    app = make_app(module_database_url, redis_settings)
    redis = Redis(
        host=redis_settings.redis_host,
        port=redis_settings.redis_port,
        db=TEST_REDIS_DATABASE,
    )

    @app.get("/api/v1/_admin")
    async def admin_only(
        claims: Annotated[TokenClaims, Depends(require_roles(AccountRoleType.ADMIN))],
    ) -> dict[str, str]:
        return {"id": claims.account_id}

    try:
        async with running_client(app) as client:
            for model in ("AccountRole", "Account"):
                await redis.set(
                    cache_key(model, {"accountId": account_id}), '["ADMIN"]'
                )

            # Act
            response = await client.get(
                "/api/v1/_admin", headers=headers_for(account_id)
            )
    finally:
        await redis.aclose()

    # Assert
    assert response.status_code == 403


async def test_a_profile_update_with_a_broken_redis_still_answers_200_and_is_stored(
    module_database_url: str,
    redis_settings: Settings,
    db_engine: AsyncEngine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    account_id, _ = await new_account(db_engine)
    app = make_app(module_database_url, redis_settings, redis_port=1)
    async with running_client(app) as client:
        # Act
        with caplog.at_level(logging.WARNING, logger="app.core.cache"):
            patched = await client.patch(
                f"/api/v1/accounts/{account_id}/profile",
                headers=headers_for(account_id),
                json={"firstName": "Ann"},
            )
        read = await client.get(ACCOUNT, headers=headers_for(account_id))

    # Assert
    assert (patched.status_code, read.json()["profile"]["firstName"]) == (200, "Ann")
    assert "read cache forget failed" in " ".join(
        record.getMessage() for record in caplog.records
    )


async def test_an_unreachable_redis_still_answers_from_the_database_and_logs_no_data(
    module_database_url: str,
    redis_settings: Settings,
    db_engine: AsyncEngine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    account_id, email = await new_account(db_engine)
    app = make_app(module_database_url, redis_settings, redis_port=1)
    async with running_client(app) as client:
        # Act
        with caplog.at_level(logging.WARNING, logger="app.core.cache"):
            response = await client.get(ACCOUNT, headers=headers_for(account_id))

    # Assert
    assert (response.status_code, response.json()["id"]) == (200, account_id)
    logged = " ".join(record.getMessage() for record in caplog.records)
    assert "read cache read failed" in logged
    assert account_id not in logged
    assert email not in logged


async def test_with_the_cache_switched_off_no_redis_is_used(
    module_database_url: str,
    redis_settings: Settings,
    db_engine: AsyncEngine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    account_id, _ = await new_account(db_engine)
    app = make_app(
        module_database_url, redis_settings, redis_port=1, cache_enabled=False
    )
    async with running_client(app) as client:
        await client.get(ACCOUNT, headers=headers_for(account_id))

        # Act
        with (
            caplog.at_level(logging.WARNING, logger="app.core.cache"),
            count_statements(statements_of(app)) as statements,
        ):
            await client.get(ACCOUNT, headers=headers_for(account_id))

    # Assert
    assert len(statements) > 0
    assert caplog.records == []


async def test_invalidate_removes_one_models_entries_from_a_real_redis(
    redis_settings: Settings,
) -> None:
    # Arrange
    cache = ReadCache(RedisCacheStore(redis_settings))
    redis = Redis(
        host=redis_settings.redis_host,
        port=redis_settings.redis_port,
        db=TEST_REDIS_DATABASE,
        decode_responses=True,
    )

    async def load() -> dict[str, str]:
        return {"x": "1"}

    try:
        for model in ("Account", "AccountRole"):
            await cache.get_or_load(
                model, {"n": 1}, load, encode=lambda v: v, decode=lambda r: r
            )

        # Act
        deleted = await cache.invalidate("Account")

        # Assert
        remaining = sorted(
            [key.split("*")[1] async for key in redis.scan_iter("cache*")]
        )
        assert (deleted, remaining) == (1, ["AccountRole"])
    finally:
        await redis.aclose()
        await cache.close()
