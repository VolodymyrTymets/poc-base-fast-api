"""The markers a test gets from its folder and its fixtures (ADR-0029)."""

import pytest
from utils.markers import UnplacedTestError, markers_for


@pytest.mark.parametrize(
    ("parts", "fixtures", "expected"),
    [
        (("unit", "test_a.py"), [], ["unit"]),
        (("integration", "db", "test_a.py"), ["db_session"], ["integration", "db"]),
        (("integration", "http", "test_a.py"), [], ["integration", "http"]),
        (
            ("integration", "http", "test_a.py"),
            ["client", "asgi_app", "module_database_url", "database_url"],
            ["integration", "http", "db"],
        ),
        (("e2e", "test_a.py"), ["redis_settings"], ["e2e", "redis"]),
        (("e2e", "test_a.py"), ["unseeded_database_url"], ["e2e", "db"]),
    ],
    ids=[
        "unit",
        "integration-db",
        "integration-http-without-database",
        "integration-http-with-database",
        "e2e-with-redis",
        "e2e-with-database",
    ],
)
def test_markers_follow_the_folder_and_the_fixtures(
    parts: tuple[str, ...], fixtures: list[str], expected: list[str]
) -> None:
    # Arrange: the path and fixture names are the parameters.

    # Act
    markers = markers_for(parts, fixtures)

    # Assert
    assert markers == expected


@pytest.mark.parametrize(
    "parts",
    [
        ("test_a.py",),
        ("other", "test_a.py"),
        ("integration", "test_a.py"),
        ("integration", "other", "test_a.py"),
    ],
    ids=["tests-root", "unknown-folder", "integration-root", "unknown-area"],
)
def test_a_test_outside_the_four_folders_is_refused(parts: tuple[str, ...]) -> None:
    # Act
    with pytest.raises(UnplacedTestError, match="is not under"):
        # Assert: the call itself raises.
        markers_for(parts, [])
