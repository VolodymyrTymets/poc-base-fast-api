from typing import Any

import pytest

from app import main


def test_run_passes_the_shutdown_timeout_and_json_logging_to_uvicorn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    levels: list[str] = []
    monkeypatch.setenv("SHUTDOWN_TIMEOUT_SECONDS", "7")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("PORT", "4100")
    # The seams: the server and the global logging setup are not started in a unit test.
    monkeypatch.setattr(
        "app.main.uvicorn.run", lambda *args, **kwargs: calls.append(kwargs)
    )
    monkeypatch.setattr(main, "configure_logging", levels.append)

    main.run()

    assert levels == ["WARNING"]
    assert calls == [
        {
            "factory": True,
            "port": 4100,
            "log_config": None,
            "timeout_graceful_shutdown": 7,
        }
    ]
