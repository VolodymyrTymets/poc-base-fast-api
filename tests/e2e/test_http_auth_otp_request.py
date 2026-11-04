"""POST /api/v1/auth/otp/request over HTTP on a real database. Task: 7.1.

The request has its own session, so rows are read through `db_engine`; they stay for the module, so each test uses a phone of its own.
"""

import logging
import re
from typing import Literal

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine
from utils.client import running_client
from utils.jwt import ACCESS_KEY, REFRESH_KEY
from utils.queue import EnqueuedJob, FakeQueue

from app.config import Settings
from app.core.logging import JsonFormatter
from app.dependencies import get_queue
from app.main import create_app
from app.models import AccountIdentity, AccountProfile

PATH = "/api/v1/auth/otp/request"
SIX_DIGITS = re.compile(r"\d{6}")

AppEnv = Literal["local", "development", "test", "production"]


class CommitCheckingQueue(FakeQueue):
    """Records, at the moment of each enqueue, whether another connection already sees the stored code hash.

    That is the proof that the route commits before it delivers: a count of jobs cannot show the order.
    """

    def __init__(
        self, engine: AsyncEngine, phone: str, fail_on: tuple[str, ...] = ()
    ) -> None:
        super().__init__(fail_on=fail_on)
        self._engine = engine
        self._phone = phone
        self.hash_seen_by_another_connection: list[bool] = []

    async def enqueue(self, job_name: str, *args: object, **kwargs: object) -> None:
        async with self._engine.connect() as connection:
            stored = await connection.scalar(
                select(AccountIdentity.otp_hash)
                .join(
                    AccountProfile,
                    AccountProfile.account_id == AccountIdentity.account_id,
                )
                .where(AccountProfile.phone_number == self._phone)
            )
        self.hash_seen_by_another_connection.append(stored is not None)
        await super().enqueue(job_name, *args, **kwargs)


def make_app(database_url: str, queue: FakeQueue, app_env: AppEnv = "local") -> FastAPI:
    app = create_app(
        Settings(
            app_env=app_env,
            database_url=database_url,
            jwt_secret=ACCESS_KEY,
            jwt_refresh_token_secret=REFRESH_KEY,
        )
    )
    app.dependency_overrides[get_queue] = lambda: queue
    return app


async def accounts_with_phone(engine: AsyncEngine, phone: str) -> int:
    async with engine.connect() as connection:
        count = await connection.scalar(
            select(func.count())
            .select_from(AccountProfile)
            .where(AccountProfile.phone_number == phone)
        )
    assert count is not None
    return count


async def test_a_new_phone_gets_the_code_in_the_body_and_one_sms_job(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    phone = "+12125550142"
    queue = FakeQueue()

    async with running_client(make_app(module_database_url, queue)) as client:
        response = await client.post(PATH, json={"phoneNumber": phone})

    body = response.json()
    assert (
        response.status_code,
        sorted(body),
        bool(SIX_DIGITS.fullmatch(body["code"])),
    ) == (
        200,
        ["code", "success"],
        True,
    )
    assert (
        body["success"],
        queue.jobs,
        await accounts_with_phone(db_engine, phone),
    ) == (
        True,
        [EnqueuedJob("send_totp_code", (phone, body["code"]), {})],
        1,
    )


async def test_the_job_is_queued_only_after_the_code_is_committed(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    phone = "+12125550144"
    queue = CommitCheckingQueue(db_engine, phone)

    async with running_client(make_app(module_database_url, queue)) as client:
        await client.post(PATH, json={"phoneNumber": phone})

    assert queue.hash_seen_by_another_connection == [True]


async def test_a_formatted_phone_is_normalised_and_a_repeat_adds_no_account(
    module_database_url: str, db_engine: AsyncEngine
) -> None:
    queue = FakeQueue()

    async with running_client(make_app(module_database_url, queue)) as client:
        await client.post(PATH, json={"phoneNumber": "+1 212-555-0143"})
        await client.post(PATH, json={"phoneNumber": "+12125550143"})

    assert (
        [job.args[0] for job in queue.jobs],
        await accounts_with_phone(db_engine, "+12125550143"),
    ) == (["+12125550143", "+12125550143"], 1)


@pytest.mark.parametrize("app_env", ["local", "development", "test"])
async def test_the_code_is_in_the_body_in_local_development_and_test(
    module_database_url: str, app_env: AppEnv
) -> None:
    queue = FakeQueue()

    async with running_client(make_app(module_database_url, queue, app_env)) as client:
        response = await client.post(PATH, json={"phoneNumber": "+12125550145"})

    assert (response.status_code, "code" in response.json()) == (200, True)


async def test_the_code_key_is_absent_from_the_body_in_production_but_still_sent_by_sms(
    module_database_url: str,
) -> None:
    queue = FakeQueue()

    async with running_client(
        make_app(module_database_url, queue, "production")
    ) as client:
        response = await client.post(PATH, json={"phoneNumber": "+12125550146"})

    assert (response.status_code, response.json(), len(queue.jobs)) == (
        200,
        {"success": True},
        1,
    )


@pytest.mark.parametrize(
    "payload",
    [{}, {"phoneNumber": "not-a-phone"}, {"phoneNumber": "+12125550147", "x": 1}],
    ids=["missing", "malformed", "extra-key"],
)
async def test_a_bad_body_is_a_validation_error_and_queues_nothing(
    module_database_url: str, db_engine: AsyncEngine, payload: dict[str, object]
) -> None:
    queue = FakeQueue()

    async with running_client(make_app(module_database_url, queue)) as client:
        response = await client.post(PATH, json=payload)

    assert (
        response.status_code,
        response.json()["error"]["code"],
        queue.jobs,
        await accounts_with_phone(db_engine, "+12125550147"),
    ) == (422, "VALIDATION_FAILED", [], 0)


async def test_with_the_queue_down_the_request_still_answers_200_with_the_code(
    module_database_url: str,
) -> None:
    queue = FakeQueue(fail_on=["send_totp_code"])

    async with running_client(make_app(module_database_url, queue)) as client:
        response = await client.post(PATH, json={"phoneNumber": "+12125550148"})

    assert (response.status_code, response.json()["success"], queue.jobs) == (
        200,
        True,
        [],
    )


async def test_no_log_line_holds_the_code_or_the_phone(
    module_database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    phone = "+12125550149"
    queue = FakeQueue(fail_on=["send_totp_code"])

    with caplog.at_level(logging.DEBUG):
        async with running_client(make_app(module_database_url, queue)) as client:
            response = await client.post(PATH, json={"phoneNumber": phone})

    formatter = JsonFormatter()
    output = "\n".join(formatter.format(record) for record in caplog.records)
    code = response.json()["code"]
    assert (code in output, phone in output) == (False, False)
