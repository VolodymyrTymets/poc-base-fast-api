import json
import logging
from collections.abc import Iterator

import pytest

from app.config import get_settings
from app.core.queue import json_deserializer, json_serializer
from app.worker import HideJobArguments, WorkerSettings, on_startup
from app.workers.email import send_password_reset
from app.workers.ping import ping
from app.workers.sms import send_totp_code


def test_retries_are_capped_at_three_and_results_are_not_kept() -> None:
    assert (WorkerSettings.max_tries, WorkerSettings.keep_result) == (3, 0)
    assert WorkerSettings.log_results is False


def test_the_jobs_are_registered_with_json_payloads() -> None:
    assert WorkerSettings.functions == [ping, send_totp_code, send_password_reset]
    assert WorkerSettings.job_serializer is json_serializer
    assert WorkerSettings.job_deserializer is json_deserializer


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


def arq_start_record(arguments: str) -> logging.LogRecord:
    # The shape of arq's own call: logger.info('%6.2fs → %s(%s)%s', seconds, ref, arguments, extra).
    return logging.LogRecord(
        "arq.worker",
        logging.INFO,
        __file__,
        1,
        "%6.2fs → %s(%s)%s",
        (0.5, "job-id:send_totp_code", arguments, " try=2"),
        None,
    )


def test_the_arguments_of_a_job_never_reach_the_log() -> None:
    record = arq_start_record("'+380000000001', '483920'")

    HideJobArguments().filter(record)

    message = record.getMessage()
    assert "483920" not in message
    assert message == "  0.50s → job-id:send_totp_code(arguments hidden) try=2"


def test_other_arq_records_pass_through_untouched() -> None:
    record = logging.LogRecord(
        "arq.worker",
        logging.INFO,
        __file__,
        1,
        "%6.2fs ← %s ● %s",
        (0.1, "id:f", ""),
        None,
    )

    assert HideJobArguments().filter(record) is True
    assert record.getMessage() == "  0.10s ← id:f ● "
