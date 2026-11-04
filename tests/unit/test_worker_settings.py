import json
import logging
from collections.abc import Iterator

import pytest

from app.config import get_settings
from app.core.queue import json_deserializer, json_serializer
from app.worker import WorkerSettings, on_startup
from app.workers.ping import ping


def test_retries_are_capped_at_three_and_results_are_not_kept() -> None:
    assert (WorkerSettings.max_tries, WorkerSettings.keep_result) == (3, 0)


def test_the_ping_job_is_registered_with_json_payloads() -> None:
    assert WorkerSettings.functions == [ping]
    assert WorkerSettings.job_serializer is json_serializer
    assert WorkerSettings.job_deserializer is json_deserializer


def test_redis_settings_come_from_the_settings_module() -> None:
    redis = WorkerSettings.redis_settings

    assert (redis.host, redis.port, redis.database) == ("localhost", 6379, 0)


@pytest.fixture
def clean_logging() -> Iterator[None]:
    root = logging.getLogger()
    saved = (root.handlers, root.level)
    arq_logger = logging.getLogger("arq")
    arq_saved = (arq_logger.handlers, arq_logger.propagate)
    yield
    root.handlers, root.level = saved
    arq_logger.handlers, arq_logger.propagate = arq_saved
    get_settings.cache_clear()


async def test_startup_makes_arq_log_redacted_json(
    clean_logging: None, capsys: pytest.CaptureFixture[str]
) -> None:
    # What arq's CLI does before on_startup: a plain handler on the `arq` logger.
    arq_logger = logging.getLogger("arq")
    arq_logger.addHandler(logging.StreamHandler())

    await on_startup({})
    capsys.readouterr()
    logging.getLogger("arq.worker").warning(
        "sent to +380000000001 with token=abc.def.ghi"
    )

    lines = capsys.readouterr().out.strip().splitlines()
    entry = json.loads(lines[0])
    assert len(lines) == 1
    assert entry["logger"] == "arq.worker"
    assert "+380000000001" not in entry["message"]
    assert "abc.def.ghi" not in entry["message"]
    assert "[REDACTED]" in entry["message"]


async def test_the_ping_job_logs_that_it_ran(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="app.workers.ping"):
        await ping({"job_try": 1})

    assert [record.getMessage() for record in caplog.records] == ["ping job ran"]
