"""`set-ports.sh`, which derives host ports for a second compose stack. Task: POC-11.2.

The script runs as its own process, from a copy placed in a temp directory, so the repo's own `.env` is never touched.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "set-ports.sh"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    shutil.copy(SCRIPT, tmp_path / "set-ports.sh")
    return tmp_path


def run(
    project: Path, *args: str, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/sh", "-c", '"$SCRIPT" $ARGUMENTS'],
        env={"SCRIPT": str(project / "set-ports.sh"), "ARGUMENTS": " ".join(args)},
        cwd=cwd or project,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def env_values(project: Path) -> dict[str, str]:
    lines = (project / ".env").read_text().splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line)


def test_base_port_gives_api_postgres_and_redis_consecutive_ports(
    project: Path,
) -> None:
    result = run(project, "4000")

    assert result.returncode == 0, result.stderr
    assert env_values(project) == {
        "EXPOSE_API_PORT": "4000",
        "EXPOSE_POSTGRES_PORT": "4001",
        "EXPOSE_REDIS_PORT": "4002",
        "PORT": "4000",
        "REDIS_PORT": "4002",
    }


def test_a_second_run_leaves_the_file_unchanged(project: Path) -> None:
    run(project, "4000")
    first = (project / ".env").read_bytes()

    result = run(project, "4000")

    assert result.returncode == 0
    assert (project / ".env").read_bytes() == first


def test_an_existing_database_url_changes_only_its_port(project: Path) -> None:
    (project / ".env").write_text(
        "DATABASE_URL=postgresql+asyncpg://user:pw@localhost:5432/poc\nLOG_LEVEL=INFO\n"
    )

    run(project, "4000")

    values = env_values(project)
    assert values["DATABASE_URL"] == "postgresql+asyncpg://user:pw@localhost:4001/poc"
    assert values["LOG_LEVEL"] == "INFO"


def test_no_database_url_line_means_none_is_added(project: Path) -> None:
    run(project, "4000")

    assert "DATABASE_URL" not in env_values(project)


def test_a_file_without_a_trailing_newline_keeps_its_last_line_intact(
    project: Path,
) -> None:
    (project / ".env").write_text("LOG_LEVEL=INFO")

    run(project, "4000")

    assert env_values(project)["LOG_LEVEL"] == "INFO"


@pytest.mark.parametrize("argument", ["abc", "1023", "65531", "-5", "40.5"])
def test_a_bad_base_port_prints_usage_and_writes_nothing(
    project: Path, argument: str
) -> None:
    result = run(project, argument)

    assert result.returncode == 1
    assert "Usage: ./set-ports.sh" in result.stderr
    assert not (project / ".env").exists()


def test_no_argument_prints_usage(project: Path) -> None:
    result = run(project)

    assert result.returncode == 1
    assert "Usage: ./set-ports.sh" in result.stderr


def test_running_from_another_directory_writes_next_to_the_script(
    project: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    elsewhere = tmp_path_factory.mktemp("elsewhere")

    result = run(project, "4000", cwd=elsewhere)

    assert result.returncode == 0
    assert (project / ".env").exists()
    assert not (elsewhere / ".env").exists()
