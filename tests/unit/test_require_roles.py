"""require_roles refuses to be built with no roles (no database needed). Task: 5.2."""

import pytest

from app.dependencies import require_roles


def test_no_roles_fails_when_the_route_is_declared() -> None:
    with pytest.raises(ValueError, match="at least one role"):
        require_roles()
