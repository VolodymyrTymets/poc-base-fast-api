"""The ordered list of seed items for an environment. Task: 5.1."""

from app.config import Settings
from app.seeds.base import SeedItem
from app.seeds.items.init_admin import InitAdmin
from app.seeds.items.init_roles import InitRoles

# The environments that also get the sample data (the Node base's local, test and development).
DEVELOPMENT_ENVS = frozenset({"local", "development", "test"})


def base_items() -> list[SeedItem]:
    """Items every environment runs. Order matters: later items (the admin, task 5.5) need the roles."""
    return [InitRoles()]


def development_items(settings: Settings) -> list[SeedItem]:
    """Sample data for `DEVELOPMENT_ENVS` only (task 5.5): the admin, then the customers (R2). They need the roles."""
    return [InitAdmin(settings)]


def seed_items(settings: Settings) -> list[SeedItem]:
    items = base_items()
    if settings.app_env in DEVELOPMENT_ENVS:
        items += development_items(settings)
    return items
