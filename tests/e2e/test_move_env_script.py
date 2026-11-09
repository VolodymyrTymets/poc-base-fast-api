"""`move-env.sh`, which carries the gitignored env files into another checkout. Task: POC-11.2.

The script runs as its own process, from a copy in a temp "source" directory with canary files, so the repo's real env files are never read.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "move-env.sh"


@pytest.fixture
def source(tmp_path: Path) -> Path:
    directory = tmp_path / "source"
    directory.mkdir()
    shutil.copy(SCRIPT, directory / "move-env.sh")
    return directory


@pytest.fixture
def target(tmp_path: Path) -> Path:
    directory = tmp_path / "target"
    directory.mkdir()
    return directory


def run(source: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/sh", "-c", '"$SCRIPT" $ARGUMENTS'],
        env={
            "SCRIPT": str(source / "move-env.sh"),
            "ARGUMENTS": " ".join(args),
            "PATH": os.environ["PATH"],
        },
        cwd=source,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_every_existing_env_file_is_copied_byte_for_byte(
    source: Path, target: Path
) -> None:
    for name in (".env", ".env.development", ".env.test"):
        (source / name).write_text(f"CANARY={name}\n")

    result = run(source, str(target))

    assert result.returncode == 0, result.stderr
    for name in (".env", ".env.development", ".env.test"):
        assert (target / name).read_bytes() == (source / name).read_bytes()
        assert f"copied {name}" in result.stdout


def test_a_missing_file_is_skipped_and_named(source: Path, target: Path) -> None:
    (source / ".env").write_text("A=1\n")

    result = run(source, str(target))

    assert result.returncode == 0
    assert "skipped .env.development (not found)" in result.stdout
    assert not (target / ".env.development").exists()


def test_no_env_file_at_all_exits_1_and_copies_nothing(
    source: Path, target: Path
) -> None:
    result = run(source, str(target))

    assert result.returncode == 1
    assert "nothing to move" in result.stderr
    assert list(target.iterdir()) == []


def test_an_existing_target_file_is_refused_and_nothing_is_copied(
    source: Path, target: Path
) -> None:
    (source / ".env").write_text("A=1\n")
    (source / ".env.test").write_text("B=2\n")
    (target / ".env.test").write_text("THEIRS=1\n")

    result = run(source, str(target))

    assert result.returncode == 1
    assert "refusing to overwrite" in result.stderr
    assert (target / ".env.test").read_text() == "THEIRS=1\n"
    assert not (target / ".env").exists()


def test_force_overwrites_an_existing_target_file(source: Path, target: Path) -> None:
    (source / ".env").write_text("A=1\n")
    (target / ".env").write_text("THEIRS=1\n")

    result = run(source, "--force", str(target))

    assert result.returncode == 0, result.stderr
    assert (target / ".env").read_text() == "A=1\n"


@pytest.mark.parametrize("arguments", [[], ["/nonexistent/dir/for/this/test"]])
def test_a_missing_or_invalid_target_prints_usage(
    source: Path, arguments: list[str]
) -> None:
    (source / ".env").write_text("A=1\n")

    result = run(source, *arguments)

    assert result.returncode == 1
    assert "Usage: ./move-env.sh" in result.stderr


def test_the_source_files_are_left_unchanged(source: Path, target: Path) -> None:
    (source / ".env").write_text("A=1\n")

    run(source, str(target))

    assert (source / ".env").read_text() == "A=1\n"


def test_a_relative_target_is_relative_to_where_the_script_was_run(
    source: Path, target: Path
) -> None:
    # Arrange
    (source / ".env").write_text("A=1\n")

    # Act
    result = subprocess.run(
        ["/bin/sh", "-c", '"$SCRIPT" ../target'],
        env={"SCRIPT": str(source / "move-env.sh"), "PATH": os.environ["PATH"]},
        cwd=source,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    # Assert
    assert (result.returncode, (target / ".env").read_text()) == (0, "A=1\n")


def test_the_target_being_this_checkout_is_refused(source: Path) -> None:
    # Arrange
    (source / ".env").write_text("A=1\n")

    # Act
    result = run(source, ".")

    # Assert
    assert (result.returncode, "this checkout" in result.stderr) == (1, True)
