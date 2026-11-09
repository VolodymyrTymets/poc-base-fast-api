"""`scripts/wait_for_postgres.py`, the wait the container entrypoint runs before it migrates. Task: POC-11.1.

The script runs as its own process, as the entrypoint runs it. Only the success case needs a database.
"""

import socket
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
CANARY = "s3cret-password-value"


def dead_port() -> int:
    # Bind and release a port: nothing listens on it afterwards, so a connection is refused at once.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def run_script(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    # The autouse fixture clears the app's variables, so nothing but `env` reaches the process; the script is named, not built, from its folder.
    return subprocess.run(
        [sys.executable, "-I", "wait_for_postgres.py"],
        cwd=SCRIPTS_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def attempt_lines(output: str) -> list[str]:
    return [line for line in output.splitlines() if line.startswith("attempt ")]


def dead_url() -> str:
    return f"postgresql+asyncpg://postgres:{CANARY}@127.0.0.1:{dead_port()}/poc"


def test_gives_up_after_exactly_the_configured_attempts() -> None:
    # Arrange
    env = {
        "DATABASE_URL": dead_url(),
        "DB_WAIT_ATTEMPTS": "3",
        "DB_WAIT_INTERVAL_SECONDS": "0",
    }

    # Act
    result = run_script(env)

    # Assert
    assert result.returncode == 1
    assert len(attempt_lines(result.stdout)) == 3, result.stdout
    assert attempt_lines(result.stdout)[-1].startswith("attempt 3/3 failed: ")


def test_the_default_is_thirty_attempts_and_the_message_names_thirty() -> None:
    # Arrange: issue I.6, the Node loop said 30 and ran 5. Only the interval is shortened.
    env = {"DATABASE_URL": dead_url(), "DB_WAIT_INTERVAL_SECONDS": "0"}

    # Act
    result = run_script(env)

    # Assert
    lines = attempt_lines(result.stdout)
    assert result.returncode == 1
    assert [line.split(" failed")[0] for line in lines] == [
        f"attempt {i}/30" for i in range(1, 31)
    ]
    assert "30 attempts" in result.stdout.splitlines()[-1]


def test_the_output_never_holds_the_password_or_the_url() -> None:
    # Arrange
    env = {
        "DATABASE_URL": dead_url(),
        "DB_WAIT_ATTEMPTS": "2",
        "DB_WAIT_INTERVAL_SECONDS": "0",
    }

    # Act
    result = run_script(env)

    # Assert
    assert CANARY not in result.stdout + result.stderr
    assert "postgresql" not in result.stdout + result.stderr


def test_a_missing_database_url_exits_2_naming_the_variable() -> None:
    # Arrange / Act
    result = run_script({})

    # Assert
    assert result.returncode == 2
    assert "DATABASE_URL" in result.stdout + result.stderr


@pytest.mark.parametrize("value", ["0", "-1", "many"])
def test_a_bad_attempt_count_exits_2_naming_the_variable(value: str) -> None:
    # Arrange
    env = {"DATABASE_URL": dead_url(), "DB_WAIT_ATTEMPTS": value}

    # Act
    result = run_script(env)

    # Assert
    assert result.returncode == 2
    assert "DB_WAIT_ATTEMPTS" in result.stdout + result.stderr


def test_succeeds_on_the_first_attempt_when_the_database_is_up(
    database_url: str,
) -> None:
    # Arrange
    env = {"DATABASE_URL": database_url, "DB_WAIT_INTERVAL_SECONDS": "0"}

    # Act
    result = run_script(env)

    # Assert
    assert result.returncode == 0, result.stdout + result.stderr
    assert attempt_lines(result.stdout) == []
    assert "reachable" in result.stdout
