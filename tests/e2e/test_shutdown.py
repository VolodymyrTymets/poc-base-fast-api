import json
import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Iterator

import httpx
import pytest

START_TIMEOUT = 20
STOP_TIMEOUT = 20


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def wait_until_healthy(url: str, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + START_TIMEOUT
    while time.monotonic() < deadline and process.poll() is None:
        try:
            if httpx.get(url, timeout=1).status_code == 200:
                return
        except httpx.TransportError:
            time.sleep(0.2)
    pytest.fail("the server did not become healthy")


@pytest.fixture
def server() -> Iterator[tuple[subprocess.Popen[str], str]]:
    port = free_port()
    # The real console-script entry point in a child process: SIGTERM and exit codes
    # cannot be observed in-process. The environment is the cleaned one (conftest).
    process = subprocess.Popen(
        [sys.executable, "-c", "from app.main import run; run()"],
        env={**os.environ, "PORT": str(port)},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    yield process, f"http://127.0.0.1:{port}/api/v1/health"
    if process.poll() is None:
        process.kill()
    process.communicate()


def test_sigterm_shuts_down_gracefully_and_logs_json(
    server: tuple[subprocess.Popen[str], str],
) -> None:
    process, health_url = server
    wait_until_healthy(health_url, process)

    process.send_signal(signal.SIGTERM)
    output, _ = process.communicate(timeout=STOP_TIMEOUT)

    messages = [json.loads(line)["message"] for line in output.splitlines()]
    # uvicorn finishes its shutdown, then re-raises the signal, so the status is the
    # signal's and not 0 (what a container reports as 143).
    assert process.returncode == -signal.SIGTERM
    assert "application startup" in messages
    assert "application shutdown" in messages
