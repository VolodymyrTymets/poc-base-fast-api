from utils.queue import EnqueuedJob, FakeQueue


async def test_jobs_are_recorded_in_the_order_they_were_enqueued() -> None:
    queue = FakeQueue()

    await queue.enqueue("send_totp_code", "+380000000001")
    await queue.enqueue("send_password_reset", "a@example.test", locale="en")
    await queue.enqueue("send_totp_code", "+380000000002")

    assert [job.name for job in queue.jobs] == [
        "send_totp_code",
        "send_password_reset",
        "send_totp_code",
    ]


async def test_arguments_are_stored_as_given() -> None:
    queue = FakeQueue()

    await queue.enqueue("send_password_reset", "a@example.test", 3, locale="en")

    assert queue.jobs == [
        EnqueuedJob("send_password_reset", ("a@example.test", 3), {"locale": "en"})
    ]


async def test_a_later_change_to_the_callers_kwargs_does_not_change_the_record() -> (
    None
):
    queue = FakeQueue()
    options: dict[str, object] = {"defer_by": 5}

    await queue.enqueue("send_totp_code", **options)
    options["defer_by"] = 99

    assert queue.jobs[0].kwargs == {"defer_by": 5}


async def test_named_returns_only_the_jobs_of_that_name() -> None:
    queue = FakeQueue()
    await queue.enqueue("send_totp_code", "+380000000001")
    await queue.enqueue("send_password_reset", "a@example.test")

    totp = queue.named("send_totp_code")

    assert [job.args for job in totp] == [("+380000000001",)]


async def test_named_with_no_match_is_empty_not_an_error() -> None:
    queue = FakeQueue()
    await queue.enqueue("send_totp_code")

    assert queue.named("never_enqueued") == []


async def test_clear_forgets_every_job() -> None:
    queue = FakeQueue()
    await queue.enqueue("send_totp_code")

    queue.clear()

    assert queue.jobs == []


async def test_the_jobs_property_is_a_copy() -> None:
    queue = FakeQueue()
    await queue.enqueue("send_totp_code")

    queue.jobs.clear()

    assert len(queue.jobs) == 1


async def test_the_queue_fixture_hands_each_test_its_own_queue(
    queue: FakeQueue,
) -> None:
    # Passes in any order; it fails only if one test's jobs leaked into the next test's fixture.
    leaked = queue.jobs
    await queue.enqueue("probe")

    assert leaked == []


async def test_the_queue_fixture_starts_empty_after_another_test_enqueued(
    queue: FakeQueue,
) -> None:
    assert queue.jobs == []
