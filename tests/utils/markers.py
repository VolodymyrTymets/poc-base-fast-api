"""Which markers a test gets, decided from its folder and the fixtures it uses (ADR-0029).

A pure function so it can be tested without running a collection; `tests/conftest.py` calls it from the collection hook.
"""

from collections.abc import Collection

LEVELS = {"unit", "integration", "e2e"}
INTEGRATION_AREAS = {"db", "http"}
# Any test that reaches the database requests one of these, directly or through `client`, `asgi_app` or `db_session`.
DATABASE_FIXTURES = {"database_url", "module_database_url", "unseeded_database_url"}
REDIS_FIXTURES = {"redis_target", "redis_settings"}


class UnplacedTestError(Exception):
    """A test lies outside tests/unit, tests/integration/{db,http} and tests/e2e."""


def markers_for(parts: tuple[str, ...], fixture_names: Collection[str]) -> list[str]:
    """`parts` is the test file's path under `tests/`, for example `("integration", "db", "test_x.py")`."""
    level = parts[0] if parts else ""
    if level not in LEVELS:
        raise UnplacedTestError(
            f"tests/{'/'.join(parts)} is not under tests/unit, tests/integration or tests/e2e"
        )
    markers = [level]
    if level == "integration":
        area = parts[1] if len(parts) > 2 else ""
        if area not in INTEGRATION_AREAS:
            raise UnplacedTestError(
                f"tests/{'/'.join(parts)} is not under tests/integration/db or tests/integration/http"
            )
        markers.append(area)
    if DATABASE_FIXTURES & set(fixture_names) and "db" not in markers:
        markers.append("db")
    if REDIS_FIXTURES & set(fixture_names):
        markers.append("redis")
    return markers
