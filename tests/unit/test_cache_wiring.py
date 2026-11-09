"""create_app builds the read cache from CACHE_ENABLED (task 9.2, ADR-0035)."""

from app.config import Settings
from app.core.cache import NullReadCache, ReadCache
from app.main import create_app


def test_a_cache_switched_off_stores_nothing() -> None:
    # Act
    app = create_app(Settings(cache_enabled=False))

    # Assert
    assert isinstance(app.state.cache, NullReadCache)


def test_a_cache_switched_on_is_a_read_cache() -> None:
    # Act
    app = create_app(Settings(cache_enabled=True))

    # Assert
    assert isinstance(app.state.cache, ReadCache)


def test_the_test_environment_builds_the_app_with_the_cache_off() -> None:
    # Act
    app = create_app(Settings())

    # Assert
    assert isinstance(app.state.cache, NullReadCache)
